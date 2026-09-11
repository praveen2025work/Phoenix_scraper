"""Local SQLite store. Single writer, idempotent inserts (span_id primary key)."""

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .models import (
    Candidate,
    CandidateDecision,
    CandidateObservation,
    Capability,
    CapabilityFilter,
    CapabilityRun,
    PromptCluster,
    QueryFilters,
    SessionRecord,
    SkillGapProposal,
    SkillMatch,
    SpanEvaluation,
    SpanRecord,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    session_id TEXT,
    project TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL DEFAULT '',
    span_kind TEXT NOT NULL DEFAULT 'UNKNOWN',
    start_time TEXT NOT NULL,
    end_time TEXT,
    latency_ms REAL,
    status_code TEXT NOT NULL DEFAULT 'OK',
    model_name TEXT,
    user_id TEXT,
    workflow_stage TEXT,
    asset_class TEXT,
    input_text TEXT NOT NULL DEFAULT '',
    output_text TEXT NOT NULL DEFAULT '',
    prompt_template TEXT,
    tokens_prompt INTEGER,
    tokens_completion INTEGER,
    tokens_total INTEGER,
    cost_usd REAL,
    attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_spans_start ON spans (start_time);
CREATE INDEX IF NOT EXISTS idx_spans_project_kind ON spans (project, span_kind);
CREATE INDEX IF NOT EXISTS idx_spans_session ON spans (session_id);

CREATE TABLE IF NOT EXISTS scrape_state (
    source TEXT PRIMARY KEY,
    watermark TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_clusters (
    cluster_id TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    representative TEXT NOT NULL,
    count INTEGER NOT NULL,
    n_sessions INTEGER NOT NULL DEFAULT 0,
    n_users INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    avg_latency_ms REAL,
    first_seen TEXT,
    last_seen TEXT,
    asset_classes TEXT NOT NULL DEFAULT '[]',
    workflow_stages TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    PRIMARY KEY (cluster_id, span_id)
);

CREATE TABLE IF NOT EXISTS skill_matches (
    cluster_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    score REAL NOT NULL,
    method TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (cluster_id, skill_name)
);

CREATE TABLE IF NOT EXISTS skill_proposals (
    cluster_id TEXT PRIMARY KEY,
    proposed_name TEXT NOT NULL,
    level TEXT NOT NULL,
    asset_class TEXT,
    capability TEXT,
    description TEXT NOT NULL DEFAULT '',
    evidence_count INTEGER NOT NULL,
    representative_prompt TEXT NOT NULL DEFAULT '',
    sample_span_ids TEXT NOT NULL DEFAULT '[]'
);

-- Span annotations in Phoenix's shape: locally computed CODE checks
-- (source='local') and HUMAN/LLM annotations pulled from Phoenix
-- (source='phoenix') share one table so they roll up together. Keying on
-- source as well as name keeps a Phoenix eval called "correctness" from
-- colliding with a local check of the same name.
CREATE TABLE IF NOT EXISTS span_evaluations (
    span_id TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'local',
    label TEXT NOT NULL DEFAULT '',
    score REAL,
    explanation TEXT NOT NULL DEFAULT '',
    annotator_kind TEXT NOT NULL DEFAULT 'CODE',
    target TEXT NOT NULL DEFAULT 'span',
    created_at TEXT,
    PRIMARY KEY (span_id, name, source)
);
CREATE INDEX IF NOT EXISTS idx_evals_name ON span_evaluations (name);
CREATE INDEX IF NOT EXISTS idx_evals_span ON span_evaluations (span_id);

-- Analysis output is replaced wholesale on each run, so without a snapshot
-- there is no way to answer "what are users asking that they weren't last
-- week". These two tables keep a bounded history of past runs purely for that
-- comparison; they are never read by the current-state queries.
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    n_spans INTEGER NOT NULL DEFAULT 0,
    n_clusters INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cluster_snapshots (
    run_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    representative TEXT NOT NULL DEFAULT '',
    count INTEGER NOT NULL DEFAULT 0,
    n_users INTEGER NOT NULL DEFAULT 0,
    skill_name TEXT,
    first_seen TEXT,
    last_seen TEXT,
    PRIMARY KEY (run_id, cluster_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT 'default',
    user_id TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    n_traces INTEGER NOT NULL DEFAULT 0,
    n_llm_spans INTEGER NOT NULL DEFAULT 0,
    n_user_turns INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    models TEXT NOT NULL DEFAULT '[]',
    first_prompt TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS capabilities (
    capability_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    filter_project TEXT,
    filter_workflow_stage TEXT,
    filter_asset_class TEXT,
    filter_model_name TEXT,
    filter_search TEXT,
    filter_search_any TEXT NOT NULL DEFAULT '[]',
    window_days INTEGER NOT NULL DEFAULT 30 CHECK (window_days > 0),
    thresholds_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_runs (
    capability_id      TEXT NOT NULL,
    run_id             TEXT NOT NULL,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    window_start       TEXT NOT NULL,
    window_end         TEXT NOT NULL,
    n_spans            INTEGER NOT NULL DEFAULT 0,
    n_in_scope_spans   INTEGER NOT NULL DEFAULT 0,
    n_clusters         INTEGER NOT NULL DEFAULT 0,
    n_rung1_candidates INTEGER NOT NULL DEFAULT 0,
    n_rung2_candidates INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'ok',
    notes_json         TEXT NOT NULL DEFAULT '[]',
    -- filename -> sha256 of each capability skills/*.md at run start (Phase C diffs)
    skill_hashes_json  TEXT NOT NULL DEFAULT '{}',
    -- Precomputed Analytics/Usage panels for this run (JSON object); NULL until built
    analytics_snapshot_json TEXT,
    PRIMARY KEY (capability_id, run_id)
);

CREATE TABLE IF NOT EXISTS capability_cluster_snapshots (
    capability_id  TEXT NOT NULL,
    run_id         TEXT NOT NULL,
    cluster_id     TEXT NOT NULL,
    signature      TEXT NOT NULL DEFAULT '',
    representative TEXT NOT NULL DEFAULT '',
    count          INTEGER NOT NULL DEFAULT 0,
    n_users        INTEGER NOT NULL DEFAULT 0,
    skill_name     TEXT,
    covered        INTEGER NOT NULL DEFAULT 0,
    in_scope       INTEGER NOT NULL DEFAULT 1,
    route_len_avg  REAL,
    long_route     INTEGER NOT NULL DEFAULT 0,
    first_seen     TEXT,
    last_seen      TEXT,
    -- JSON list of the asset classes this cluster was seen in. Needed to rebuild
    -- gap proposals per capability: a pattern asked across several asset classes
    -- is NOT an asset-class skill, and level inference cannot tell without it.
    asset_classes  TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (capability_id, run_id, cluster_id)
);

CREATE TABLE IF NOT EXISTS capability_cluster_members (
    capability_id TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    cluster_id    TEXT NOT NULL,
    span_id       TEXT NOT NULL,
    PRIMARY KEY (capability_id, run_id, cluster_id, span_id)
);
CREATE INDEX IF NOT EXISTS idx_cap_members_run
    ON capability_cluster_members (capability_id, run_id);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id        TEXT PRIMARY KEY,
    capability_id       TEXT NOT NULL,
    rung                TEXT NOT NULL,
    subtype             TEXT NOT NULL DEFAULT '',
    cluster_id          TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    signature           TEXT NOT NULL DEFAULT '',
    matched_skill       TEXT,
    status              TEXT NOT NULL DEFAULT 'new',
    first_seen_run_id   TEXT NOT NULL,
    first_seen_at       TEXT NOT NULL,
    last_seen_run_id    TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    ready_at            TEXT,
    promoted_at         TEXT,
    promoted_artifact_paths_json TEXT NOT NULL DEFAULT '[]',
    snooze_until_run    INTEGER,
    dismiss_reason      TEXT,
    decided_by          TEXT,
    decided_at          TEXT,
    current_evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_candidates_capability
    ON candidates (capability_id, rung, status);

CREATE TABLE IF NOT EXISTS candidate_observations (
    candidate_id       TEXT NOT NULL,
    run_id             TEXT NOT NULL,
    observed_at        TEXT NOT NULL,
    count              INTEGER NOT NULL DEFAULT 0,
    n_users            INTEGER NOT NULL DEFAULT 0,
    n_sessions         INTEGER NOT NULL DEFAULT 0,
    total_cost_usd     REAL NOT NULL DEFAULT 0,
    score              REAL,
    signals_json       TEXT NOT NULL DEFAULT '{}',
    met_evidence_bar   INTEGER NOT NULL DEFAULT 0,
    crossed_threshold  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (candidate_id, run_id)
);

CREATE TABLE IF NOT EXISTS candidate_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL,
    run_id       TEXT,
    action       TEXT NOT NULL,
    actor        TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cand_decisions ON candidate_decisions (candidate_id, id);

CREATE TABLE IF NOT EXISTS capability_jobs (
    job_id        TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'queued'
                  CHECK (state IN ('queued', 'running', 'done', 'error')),
    -- Fine-grained UI progress: queued -> scraping -> analyzing -> matching -> done|error
    stage         TEXT NOT NULL DEFAULT 'queued',
    progress      REAL NOT NULL DEFAULT 0,
    message       TEXT,
    params_json   TEXT NOT NULL DEFAULT '{}',
    run_id        TEXT,
    error         TEXT,
    enqueued_at   TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_capability_jobs_cap
    ON capability_jobs (capability_id, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_capability_jobs_state
    ON capability_jobs (state, enqueued_at);
"""


# `CREATE TABLE IF NOT EXISTS` upgrades a DB with a NEW table, but never adds a
# column to one that already exists. Columns added after a table shipped go here
# and are applied idempotently on every open.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("capability_cluster_snapshots", "asset_classes", "TEXT NOT NULL DEFAULT '[]'"),
    ("capabilities", "filter_search_any", "TEXT NOT NULL DEFAULT '[]'"),
    ("capability_jobs", "stage", "TEXT NOT NULL DEFAULT 'queued'"),
    ("capability_jobs", "progress", "REAL NOT NULL DEFAULT 0"),
    ("capability_jobs", "message", "TEXT"),
    ("capability_runs", "skill_hashes_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("capability_runs", "analytics_snapshot_json", "TEXT"),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


class Store:
    """Thin wrapper over sqlite3 — every method opens/uses one connection owned by the store."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.executescript(_SCHEMA)
        _add_missing_columns(self._conn)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---- spans -------------------------------------------------------------
    def upsert_spans(self, records: Iterable[SpanRecord]) -> int:
        """Idempotent insert; returns number of newly inserted rows."""
        rows = [
            (
                r.span_id, r.trace_id, r.session_id, r.project, r.name, r.span_kind,
                _iso(r.start_time), _iso(r.end_time), r.latency_ms, r.status_code,
                r.model_name, r.user_id, r.workflow_stage, r.asset_class,
                r.input_text, r.output_text, r.prompt_template,
                r.tokens_prompt, r.tokens_completion, r.tokens_total, r.cost_usd,
                json.dumps(r.attributes, default=str),
            )
            for r in records
        ]
        before = self._count("spans")
        self._conn.executemany(
            "INSERT OR IGNORE INTO spans VALUES (" + ",".join(["?"] * 22) + ")", rows
        )
        self._conn.commit()
        return self._count("spans") - before

    def spans_frame(self, filters: QueryFilters | None = None) -> pd.DataFrame:
        f = filters or QueryFilters()
        where, params = _span_where(f)
        sql = f"SELECT * FROM spans{where} ORDER BY start_time LIMIT ?"
        df = pd.read_sql_query(sql, self._conn, params=[*params, f.limit])
        for col in ("start_time", "end_time"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df

    def update_span_costs(self, costs: dict[str, float]) -> None:
        """Persist computed cost_usd per span_id."""
        self._conn.executemany(
            "UPDATE spans SET cost_usd = ? WHERE span_id = ?",
            [(v, k) for k, v in costs.items()],
        )
        self._conn.commit()

    # ---- watermark ----------------------------------------------------------
    def get_watermark(self, source: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT watermark FROM scrape_state WHERE source = ?", (source,)
        ).fetchone()
        if row is None or row["watermark"] is None:
            return None
        return datetime.fromisoformat(row["watermark"])

    def set_watermark(self, source: str, watermark: datetime) -> None:
        self._conn.execute(
            "INSERT INTO scrape_state (source, watermark, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET watermark = excluded.watermark, "
            "updated_at = excluded.updated_at",
            (source, _iso(watermark), _iso(datetime.now(UTC))),
        )
        self._conn.commit()

    def clear_watermark(self, source: str) -> bool:
        """Forget a source's scrape watermark so the next pull can go back to
        --since / full history. Returns True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM scrape_state WHERE source = ?", (source,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ---- analysis results ---------------------------------------------------
    def replace_analysis(
        self,
        clusters: Iterable[PromptCluster],
        matches: Iterable[SkillMatch],
        proposals: Iterable[SkillGapProposal],
        sessions: Iterable[SessionRecord],
    ) -> None:
        """Analysis output is derived data — replaced wholesale on each run."""
        c = self._conn
        c.execute("DELETE FROM prompt_clusters")
        c.execute("DELETE FROM cluster_members")
        c.execute("DELETE FROM skill_matches")
        c.execute("DELETE FROM skill_proposals")
        c.execute("DELETE FROM sessions")
        for cl in clusters:
            c.execute(
                "INSERT INTO prompt_clusters VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cl.cluster_id, cl.signature, cl.representative, cl.count,
                    cl.n_sessions, cl.n_users, cl.total_cost_usd, cl.avg_latency_ms,
                    _iso(cl.first_seen), _iso(cl.last_seen),
                    json.dumps(list(cl.asset_classes)), json.dumps(list(cl.workflow_stages)),
                ),
            )
            c.executemany(
                "INSERT OR IGNORE INTO cluster_members VALUES (?, ?)",
                [(cl.cluster_id, sid) for sid in cl.span_ids],
            )
        c.executemany(
            "INSERT OR REPLACE INTO skill_matches VALUES (?,?,?,?)",
            [(m.cluster_id, m.skill_name, m.score, m.method) for m in matches],
        )
        c.executemany(
            "INSERT OR REPLACE INTO skill_proposals VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    p.cluster_id, p.proposed_name, p.level, p.asset_class, p.capability,
                    p.description, p.evidence_count, p.representative_prompt,
                    json.dumps(list(p.sample_span_ids)),
                )
                for p in proposals
            ],
        )
        c.executemany(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    s.session_id, s.project, s.user_id, _iso(s.start_time), _iso(s.end_time),
                    s.n_traces, s.n_llm_spans, s.n_user_turns, s.total_tokens,
                    s.total_cost_usd, json.dumps(list(s.models)), s.first_prompt,
                )
                for s in sessions
            ],
        )
        c.commit()

    # ---- run history (for run-over-run diffing) ------------------------------
    def record_run(
        self,
        run_id: str,
        generated_at: datetime,
        clusters: Iterable[PromptCluster],
        matches: Iterable[SkillMatch],
        n_spans: int,
        history_limit: int = 20,
    ) -> str:
        """Snapshot this run's clusters so the next run can diff against it.

        Older runs beyond ``history_limit`` are pruned — the history exists to
        answer "what changed", not to be an archive, and an unbounded snapshot
        table would dwarf the spans it describes.
        """
        skill_by_cluster = {m.cluster_id: m.skill_name for m in matches}
        rows = [
            (
                run_id, c.cluster_id, c.representative, c.count, c.n_users,
                skill_by_cluster.get(c.cluster_id), _iso(c.first_seen), _iso(c.last_seen),
            )
            for c in clusters
        ]
        self._conn.execute(
            "INSERT OR REPLACE INTO analysis_runs VALUES (?,?,?,?)",
            (run_id, _iso(generated_at), n_spans, len(rows)),
        )
        self._conn.execute("DELETE FROM cluster_snapshots WHERE run_id = ?", (run_id,))
        self._conn.executemany(
            "INSERT OR REPLACE INTO cluster_snapshots VALUES (?,?,?,?,?,?,?,?)", rows
        )
        self._prune_runs(history_limit)
        self._conn.commit()
        return run_id

    def runs_frame(self, limit: int = 50) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM analysis_runs ORDER BY generated_at DESC LIMIT ?",
            self._conn,
            params=[limit],
        )

    def previous_run_id(self, before: str | None = None) -> str | None:
        """The run recorded immediately before ``before`` (or the latest run)."""
        if before is None:
            row = self._conn.execute(
                "SELECT run_id FROM analysis_runs ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT run_id FROM analysis_runs WHERE generated_at < "
                "(SELECT generated_at FROM analysis_runs WHERE run_id = ?) "
                "ORDER BY generated_at DESC LIMIT 1",
                (before,),
            ).fetchone()
        return row["run_id"] if row else None

    def run_snapshot_frame(self, run_id: str | None) -> pd.DataFrame:
        if run_id is None:
            return pd.DataFrame(columns=_SNAPSHOT_COLUMNS)
        return pd.read_sql_query(
            "SELECT * FROM cluster_snapshots WHERE run_id = ? ORDER BY count DESC",
            self._conn,
            params=[run_id],
        )

    def _prune_runs(self, history_limit: int) -> None:
        keep = max(1, history_limit)
        stale = [
            row["run_id"]
            for row in self._conn.execute(
                "SELECT run_id FROM analysis_runs ORDER BY generated_at DESC "
                "LIMIT -1 OFFSET ?",
                (keep,),
            ).fetchall()
        ]
        if not stale:
            return
        placeholders = ",".join("?" * len(stale))
        self._conn.execute(
            f"DELETE FROM cluster_snapshots WHERE run_id IN ({placeholders})",  # noqa: S608
            stale,
        )
        self._conn.execute(
            f"DELETE FROM analysis_runs WHERE run_id IN ({placeholders})",  # noqa: S608
            stale,
        )

    # ---- span evaluations (validation) --------------------------------------
    def replace_local_evaluations(self, evaluations: Iterable[SpanEvaluation]) -> int:
        """Swap in a fresh set of locally computed checks.

        Only source='local' rows are cleared: annotations pulled from Phoenix are
        that server's data, not ours to discard on a re-analysis.
        """
        rows = [_evaluation_row(e) for e in evaluations]
        self._conn.execute("DELETE FROM span_evaluations WHERE source = 'local'")
        self._conn.executemany(
            "INSERT OR REPLACE INTO span_evaluations VALUES (?,?,?,?,?,?,?,?,?)", rows
        )
        self._conn.commit()
        return len(rows)

    def upsert_evaluations(self, evaluations: Iterable[SpanEvaluation]) -> int:
        """Idempotent insert used for incrementally pulled Phoenix annotations."""
        rows = [_evaluation_row(e) for e in evaluations]
        before = self._count("span_evaluations")
        self._conn.executemany(
            "INSERT OR REPLACE INTO span_evaluations VALUES (?,?,?,?,?,?,?,?,?)", rows
        )
        self._conn.commit()
        return self._count("span_evaluations") - before

    def evaluations_frame(self, filters: QueryFilters | None = None) -> pd.DataFrame:
        """Judgements joined to their span, filtered on the span's dimensions.

        The join is what makes validation slice by user/model/stage like every
        other panel: the filters describe spans, the rows describe checks.

        NOTE: ``filters.limit`` bounds returned CHECK ROWS, not spans — a span
        carries one row per applicable check. Callers computing rollups must
        pass a limit sized for rows (see api.EVALUATION_ROW_LIMIT), or the
        aggregates silently describe a truncated corpus.
        """
        f = filters or QueryFilters()
        where, params = _span_where(f, alias="s")
        sql = (
            "SELECT e.span_id, e.name, e.source, e.label, e.score, e.explanation, "
            "e.annotator_kind, e.target, e.created_at, "
            "s.trace_id, s.session_id, s.project, s.user_id, s.model_name, "
            "s.workflow_stage, s.asset_class, s.span_kind, s.status_code, "
            "s.start_time, s.latency_ms, s.tokens_total, s.cost_usd, "
            "s.input_text, s.output_text "
            f"FROM span_evaluations e JOIN spans s ON s.span_id = e.span_id{where} "
            "ORDER BY s.start_time, e.name LIMIT ?"
        )
        df = pd.read_sql_query(sql, self._conn, params=[*params, f.limit])
        if "start_time" in df.columns:
            df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
        return df

    def clusters_frame(self, min_count: int = 1, limit: int = 500) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM prompt_clusters WHERE count >= ? ORDER BY count DESC LIMIT ?",
            self._conn,
            params=[min_count, limit],
        )

    def distinct_options(self) -> dict:
        """Distinct filterable values plus the span time range (for UI filters)."""

        def column(name: str) -> list[str]:
            rows = self._conn.execute(
                f"SELECT DISTINCT {name} FROM spans "  # noqa: S608 — internal literals
                f"WHERE {name} IS NOT NULL AND {name} != '' ORDER BY {name}"
            ).fetchall()
            return [row[0] for row in rows]

        first, last = self._conn.execute(
            "SELECT MIN(start_time), MAX(start_time) FROM spans"
        ).fetchone()
        return {
            "projects": column("project"),
            "users": column("user_id"),
            "workflow_stages": column("workflow_stage"),
            "asset_classes": column("asset_class"),
            "models": column("model_name"),
            "min_time": first,
            "max_time": last,
        }

    def cluster_members_frame(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT cluster_id, span_id FROM cluster_members", self._conn
        )

    def matches_frame(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT m.*, c.representative, c.count FROM skill_matches m "
            "JOIN prompt_clusters c ON c.cluster_id = m.cluster_id "
            "ORDER BY c.count DESC, m.score DESC",
            self._conn,
        )

    def proposals_frame(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM skill_proposals ORDER BY evidence_count DESC", self._conn
        )

    def sessions_frame(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM sessions ORDER BY start_time DESC", self._conn
        )

    # ---- capabilities --------------------------------------------------------
    def upsert_capability(self, capability: Capability) -> None:
        """Mirror a Capability into the table. created_at is preserved on update."""
        now = _iso(datetime.now(UTC))
        f = capability.filter
        self._conn.execute(
            "INSERT INTO capabilities (capability_id, name, description, "
            "filter_project, filter_workflow_stage, filter_asset_class, "
            "filter_model_name, filter_search, filter_search_any, window_days, "
            "thresholds_json, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(capability_id) DO UPDATE SET "
            "name=excluded.name, description=excluded.description, "
            "filter_project=excluded.filter_project, "
            "filter_workflow_stage=excluded.filter_workflow_stage, "
            "filter_asset_class=excluded.filter_asset_class, "
            "filter_model_name=excluded.filter_model_name, "
            "filter_search=excluded.filter_search, "
            "filter_search_any=excluded.filter_search_any, "
            "window_days=excluded.window_days, "
            "thresholds_json=excluded.thresholds_json, "
            "status=excluded.status, updated_at=excluded.updated_at",
            (
                capability.id, capability.name, capability.description,
                f.project, f.workflow_stage, f.asset_class, f.model_name, f.search,
                json.dumps(list(f.search_any)),
                capability.window_days, json.dumps(capability.thresholds),
                capability.status, now, now,
            ),
        )
        self._conn.commit()

    def get_capability(self, capability_id: str) -> Capability | None:
        row = self._conn.execute(
            "SELECT * FROM capabilities WHERE capability_id = ?", (capability_id,)
        ).fetchone()
        return _capability_from_row(row) if row is not None else None

    def capabilities_frame(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM capabilities ORDER BY capability_id", self._conn
        )

    def delete_capability(self, capability_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM capabilities WHERE capability_id = ?", (capability_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ---- capability jobs (async run queue) -----------------------------------
    def enqueue_job(self, job_id: str, capability_id: str, params: dict) -> None:
        self._conn.execute(
            "INSERT INTO capability_jobs "
            "(job_id, capability_id, state, stage, progress, message, params_json, "
            "enqueued_at) VALUES (?,?,'queued','queued',0,NULL,?,?)",
            (job_id, capability_id, json.dumps(params), _iso(datetime.now(UTC))),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM capability_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return _job_from_row(row) if row is not None else None

    def capability_jobs_frame(self, capability_id: str, limit: int = 50) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM capability_jobs WHERE capability_id = ? "
            "ORDER BY enqueued_at DESC LIMIT ?",
            self._conn, params=[capability_id, limit],
        )

    def claim_next_job(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM capability_jobs WHERE state = 'queued' "
            "ORDER BY enqueued_at LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        now = _iso(datetime.now(UTC))
        self._conn.execute(
            "UPDATE capability_jobs SET state = 'running', started_at = ?, "
            "stage = 'scraping', progress = 0.05, message = 'Starting scrape' "
            "WHERE job_id = ?",
            (now, row["job_id"]),
        )
        self._conn.commit()
        job = _job_from_row(row)
        job["state"] = "running"
        job["started_at"] = now
        job["stage"] = "scraping"
        job["progress"] = 0.05
        job["message"] = "Starting scrape"
        return job

    def update_job_progress(
        self,
        job_id: str,
        *,
        stage: str,
        progress: float,
        message: str | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE capability_jobs SET stage = ?, progress = ?, message = ? "
            "WHERE job_id = ?",
            (stage, float(progress), message, job_id),
        )
        self._conn.commit()

    def finish_job(
        self, job_id: str, *, run_id: str | None, state: str,
        error: str | None = None, message: str | None = None,
    ) -> None:
        stage = "done" if state == "done" else "error"
        self._conn.execute(
            "UPDATE capability_jobs SET state = ?, stage = ?, progress = 1.0, "
            "run_id = ?, error = ?, message = ?, finished_at = ? WHERE job_id = ?",
            (
                state, stage, run_id, error,
                message if message is not None else error,
                _iso(datetime.now(UTC)), job_id,
            ),
        )
        self._conn.commit()

    def reset_orphaned_jobs(self) -> int:
        cur = self._conn.execute(
            "UPDATE capability_jobs SET state = 'error', stage = 'error', "
            "progress = 1.0, error = 'interrupted by restart', "
            "message = 'interrupted by restart', finished_at = ? "
            "WHERE state IN ('queued', 'running')",
            (_iso(datetime.now(UTC)),),
        )
        self._conn.commit()
        return cur.rowcount

    def candidates_observed_in_run(
        self, capability_id: str, run_id: str
    ) -> pd.DataFrame:
        """Candidates that have an observation row for this capability run."""
        return pd.read_sql_query(
            "SELECT c.* FROM candidates c "
            "WHERE c.capability_id = ? AND c.candidate_id IN ("
            "  SELECT candidate_id FROM candidate_observations WHERE run_id = ?"
            ") ORDER BY c.rung, c.status, c.last_seen_at DESC",
            self._conn, params=[capability_id, run_id],
        )

    def get_capability_run(self, capability_id: str, run_id: str) -> dict | None:
        """One capability_runs row by primary key, or None."""
        row = self._conn.execute(
            "SELECT * FROM capability_runs WHERE capability_id = ? AND run_id = ?",
            (capability_id, run_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_analytics_snapshot(
        self, capability_id: str, run_id: str
    ) -> dict[str, Any] | None:
        """Parsed analytics_snapshot_json for a run, or None if missing/empty."""
        row = self._conn.execute(
            "SELECT analytics_snapshot_json FROM capability_runs "
            "WHERE capability_id = ? AND run_id = ?",
            (capability_id, run_id),
        ).fetchone()
        if row is None or not row["analytics_snapshot_json"]:
            return None
        try:
            parsed = json.loads(row["analytics_snapshot_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) and parsed else None

    def set_analytics_snapshot(
        self, capability_id: str, run_id: str, snapshot: dict[str, Any]
    ) -> None:
        """Persist a precomputed Analytics panel payload on an existing run."""
        cur = self._conn.execute(
            "UPDATE capability_runs SET analytics_snapshot_json = ? "
            "WHERE capability_id = ? AND run_id = ?",
            (json.dumps(snapshot), capability_id, run_id),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(
                f"No capability run found: {capability_id}/{run_id}"
            )

    # ---- capability runs ------------------------------------------------------
    def span_count(self) -> int:
        return self._count("spans")

    def record_capability_run(
        self,
        run: CapabilityRun,
        snapshot_rows: list[dict],
        member_rows: list[tuple[str, str]],
        history_limit: int,
        *,
        analytics_snapshot: dict | None = None,
    ) -> None:
        """Write the run row, replace this run's snapshots + members, prune."""
        c = self._conn
        # Preserve an existing analytics snapshot when the caller does not pass one
        # (e.g. failed-run REPLACE) — successful analysis always passes a fresh dict.
        snap_json: str | None
        if analytics_snapshot is not None:
            snap_json = json.dumps(analytics_snapshot)
        else:
            existing = c.execute(
                "SELECT analytics_snapshot_json FROM capability_runs "
                "WHERE capability_id = ? AND run_id = ?",
                (run.capability_id, run.run_id),
            ).fetchone()
            if existing is not None and "analytics_snapshot_json" in existing.keys():
                snap_json = existing["analytics_snapshot_json"]
            else:
                snap_json = None
        c.execute(
            "INSERT OR REPLACE INTO capability_runs (capability_id, run_id, "
            "started_at, finished_at, window_start, window_end, n_spans, "
            "n_in_scope_spans, n_clusters, n_rung1_candidates, n_rung2_candidates, "
            "status, notes_json, skill_hashes_json, analytics_snapshot_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.capability_id, run.run_id, _iso(run.started_at),
                _iso(run.finished_at), _iso(run.window_start), _iso(run.window_end),
                run.n_spans, run.n_in_scope_spans, run.n_clusters,
                run.n_rung1_candidates, run.n_rung2_candidates, run.status,
                json.dumps(list(run.notes)), json.dumps(dict(run.skill_hashes)),
                snap_json,
            ),
        )
        c.execute(
            "DELETE FROM capability_cluster_snapshots WHERE capability_id = ? AND run_id = ?",
            (run.capability_id, run.run_id),
        )
        c.execute(
            "DELETE FROM capability_cluster_members WHERE capability_id = ? AND run_id = ?",
            (run.capability_id, run.run_id),
        )
        # asset_classes arrived after the table shipped; default it so a caller
        # building rows by hand does not have to know about it.
        snapshot_rows = [{"asset_classes": "[]", **row} for row in snapshot_rows]
        c.executemany(
            "INSERT INTO capability_cluster_snapshots (capability_id, run_id, "
            "cluster_id, signature, representative, count, n_users, skill_name, "
            "covered, in_scope, route_len_avg, long_route, first_seen, last_seen, "
            "asset_classes) "
            "VALUES (:capability_id,:run_id,:cluster_id,:signature,:representative,"
            ":count,:n_users,:skill_name,:covered,:in_scope,:route_len_avg,"
            ":long_route,:first_seen,:last_seen,:asset_classes)",
            snapshot_rows,
        )
        c.executemany(
            "INSERT OR IGNORE INTO capability_cluster_members "
            "(capability_id, run_id, cluster_id, span_id) VALUES (?,?,?,?)",
            [(run.capability_id, run.run_id, cid, sid) for cid, sid in member_rows],
        )
        self._prune_capability_runs(run.capability_id, history_limit)
        c.commit()

    def capability_runs_frame(self, capability_id: str, limit: int = 50) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM capability_runs WHERE capability_id = ? "
            "ORDER BY run_id DESC LIMIT ?",
            self._conn, params=[capability_id, limit],
        )

    def previous_capability_run_id(
        self, capability_id: str, before: str | None = None
    ) -> str | None:
        if before is None:
            row = self._conn.execute(
                "SELECT run_id FROM capability_runs WHERE capability_id = ? "
                "ORDER BY run_id DESC LIMIT 1",
                (capability_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT run_id FROM capability_runs WHERE capability_id = ? "
                "AND run_id < ? ORDER BY run_id DESC LIMIT 1",
                (capability_id, before),
            ).fetchone()
        return row["run_id"] if row else None

    def capability_run_snapshot_frame(
        self, capability_id: str, run_id: str | None
    ) -> pd.DataFrame:
        if run_id is None:
            return pd.DataFrame(columns=_CAP_SNAPSHOT_COLUMNS)
        return pd.read_sql_query(
            "SELECT * FROM capability_cluster_snapshots "
            "WHERE capability_id = ? AND run_id = ? ORDER BY count DESC",
            self._conn, params=[capability_id, run_id],
        )

    def capability_cluster_members_frame(
        self, capability_id: str, run_id: str
    ) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT cluster_id, span_id FROM capability_cluster_members "
            "WHERE capability_id = ? AND run_id = ?",
            self._conn, params=[capability_id, run_id],
        )

    def latest_capability_run_id_on_day(
        self, capability_id: str, day: str
    ) -> str | None:
        row = self._conn.execute(
            "SELECT run_id FROM capability_runs WHERE capability_id = ? "
            "AND run_id LIKE ? ORDER BY run_id DESC LIMIT 1",
            (capability_id, f"{day}%"),
        ).fetchone()
        return row["run_id"] if row else None

    def _prune_capability_runs(self, capability_id: str, history_limit: int) -> None:
        keep = max(1, history_limit)
        stale = [
            row["run_id"]
            for row in self._conn.execute(
                "SELECT run_id FROM capability_runs WHERE capability_id = ? "
                "ORDER BY run_id DESC LIMIT -1 OFFSET ?",
                (capability_id, keep),
            ).fetchall()
        ]
        if not stale:
            return
        placeholders = ",".join("?" * len(stale))
        for table in (
            "capability_runs",
            "capability_cluster_snapshots",
            "capability_cluster_members",
        ):
            self._conn.execute(
                f"DELETE FROM {table} WHERE capability_id = ? "  # noqa: S608 — table name is a literal
                f"AND run_id IN ({placeholders})",
                [capability_id, *stale],
            )

    # ---- ladder candidates --------------------------------------------------
    def upsert_candidate(self, candidate: Candidate) -> None:
        c = self._conn
        c.execute(
            "INSERT OR REPLACE INTO candidates ("
            "candidate_id, capability_id, rung, subtype, cluster_id, title, "
            "signature, matched_skill, status, first_seen_run_id, first_seen_at, "
            "last_seen_run_id, last_seen_at, ready_at, promoted_at, "
            "promoted_artifact_paths_json, snooze_until_run, dismiss_reason, "
            "decided_by, decided_at, current_evidence_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                candidate.candidate_id, candidate.capability_id, candidate.rung,
                candidate.subtype, candidate.cluster_id, candidate.title,
                candidate.signature, candidate.matched_skill, candidate.status,
                candidate.first_seen_run_id, _iso(candidate.first_seen_at),
                candidate.last_seen_run_id, _iso(candidate.last_seen_at),
                _iso(candidate.ready_at), _iso(candidate.promoted_at),
                json.dumps(list(candidate.promoted_artifact_paths)),
                candidate.snooze_until_run, candidate.dismiss_reason,
                candidate.decided_by, _iso(candidate.decided_at),
                json.dumps(candidate.current_evidence),
            ),
        )
        c.commit()

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        row = self._conn.execute(
            "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return _candidate_from_row(row) if row is not None else None

    def candidates_frame(
        self, capability_id: str, *, rung: str | None = None, status: str | None = None
    ) -> pd.DataFrame:
        clauses = ["capability_id = ?"]
        params: list = [capability_id]
        if rung is not None:
            clauses.append("rung = ?")
            params.append(rung)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        return pd.read_sql_query(
            f"SELECT * FROM candidates WHERE {' AND '.join(clauses)} "  # noqa: S608 — literal clauses
            "ORDER BY status, last_seen_at DESC",
            self._conn, params=params,
        )

    def record_candidate_observation(self, obs: CandidateObservation) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO candidate_observations ("
            "candidate_id, run_id, observed_at, count, n_users, n_sessions, "
            "total_cost_usd, score, signals_json, met_evidence_bar, crossed_threshold"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                obs.candidate_id, obs.run_id, _iso(obs.observed_at), obs.count,
                obs.n_users, obs.n_sessions, obs.total_cost_usd, obs.score,
                json.dumps(obs.signals), int(obs.met_evidence_bar),
                int(obs.crossed_threshold),
            ),
        )
        self._conn.commit()

    def candidate_observations_frame(self, candidate_id: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM candidate_observations WHERE candidate_id = ? "
            "ORDER BY run_id",
            self._conn, params=[candidate_id],
        )

    def recent_candidate_observations(
        self, candidate_id: str, n: int
    ) -> list[CandidateObservation]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_observations WHERE candidate_id = ? "
            "ORDER BY run_id DESC LIMIT ?",
            (candidate_id, n),
        ).fetchall()
        return [_observation_from_row(row) for row in rows]

    def record_candidate_decision(self, decision: CandidateDecision) -> int:
        cur = self._conn.execute(
            "INSERT INTO candidate_decisions (candidate_id, run_id, action, actor, "
            "note, created_at) VALUES (?,?,?,?,?,?)",
            (
                decision.candidate_id, decision.run_id, decision.action,
                decision.actor, decision.note, _iso(decision.created_at),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def candidate_decisions_frame(self, candidate_id: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM candidate_decisions WHERE candidate_id = ? ORDER BY id",
            self._conn, params=[candidate_id],
        )

    def record_candidate_decision_now(
        self, candidate_id: str, action: str, actor: str, when: datetime,
        *, note: str = "", run_id: str | None = None,
    ) -> int:
        """Convenience: build + record a CandidateDecision in one call."""
        return self.record_candidate_decision(CandidateDecision(
            candidate_id=candidate_id, run_id=run_id, action=action, actor=actor,
            note=note, created_at=when,
        ))

    def capability_run_ordinal(
        self, capability_id: str, run_id: str | None = None
    ) -> int:
        if run_id is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM capability_runs WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM capability_runs WHERE capability_id = ? "
                "AND run_id <= ?",
                (capability_id, run_id),
            ).fetchone()
        return int(row["n"])

    def prune_candidate_observations(self, candidate_id: str, keep: int) -> None:
        stale = [
            row["run_id"]
            for row in self._conn.execute(
                "SELECT run_id FROM candidate_observations WHERE candidate_id = ? "
                "ORDER BY run_id DESC LIMIT -1 OFFSET ?",
                (candidate_id, max(1, keep)),
            ).fetchall()
        ]
        if not stale:
            return
        placeholders = ",".join("?" * len(stale))
        self._conn.execute(
            "DELETE FROM candidate_observations WHERE candidate_id = ? "  # noqa: S608 — placeholders only
            f"AND run_id IN ({placeholders})",
            [candidate_id, *stale],
        )
        self._conn.commit()

    # ---- internals -----------------------------------------------------------
    def _count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


_SNAPSHOT_COLUMNS = [
    "run_id", "cluster_id", "representative", "count", "n_users", "skill_name",
    "first_seen", "last_seen",
]

_CAP_SNAPSHOT_COLUMNS = [
    "capability_id", "run_id", "cluster_id", "signature", "representative",
    "count", "n_users", "skill_name", "covered", "in_scope", "route_len_avg",
    "long_route", "first_seen", "last_seen", "asset_classes",
]


def _evaluation_row(evaluation: SpanEvaluation) -> tuple:
    return (
        evaluation.span_id, evaluation.name, evaluation.source, evaluation.label,
        evaluation.score, evaluation.explanation, evaluation.annotator_kind,
        evaluation.target, _iso(evaluation.created_at),
    )


def _row_get(row: object, key: str, default: object = None) -> object:
    """Column lookup tolerant of a sqlite3.Row (which has no .get) and of a row
    that predates a column — used for fields added after the table shipped."""
    try:
        value = row[key]  # type: ignore[index]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _capability_from_row(row: sqlite3.Row) -> Capability:
    window_days = int(row["window_days"])
    status = row["status"]
    return Capability(
        id=row["capability_id"],
        name=row["name"],
        description=row["description"],
        filter=CapabilityFilter(
            project=row["filter_project"],
            workflow_stage=row["filter_workflow_stage"],
            asset_class=row["filter_asset_class"],
            model_name=row["filter_model_name"],
            search=row["filter_search"],
            search_any=tuple(json.loads(_row_get(row, "filter_search_any") or "[]")),
        ),
        window_days=window_days if window_days > 0 else 30,
        thresholds=json.loads(row["thresholds_json"]),
        status=status if status in ("active", "paused") else "active",
    )


def _job_from_row(row: sqlite3.Row) -> dict:
    keys = set(row.keys())
    return {
        "job_id": row["job_id"],
        "capability_id": row["capability_id"],
        "state": row["state"],
        "stage": row["stage"] if "stage" in keys else "queued",
        "progress": float(row["progress"]) if "progress" in keys and row["progress"] is not None else 0.0,
        "message": row["message"] if "message" in keys else None,
        "params": json.loads(row["params_json"]),
        "run_id": row["run_id"],
        "error": row["error"],
        "enqueued_at": row["enqueued_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _dt_or_none(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _candidate_from_row(row: sqlite3.Row) -> Candidate:
    return Candidate(
        candidate_id=row["candidate_id"],
        capability_id=row["capability_id"],
        rung=row["rung"],
        subtype=row["subtype"],
        cluster_id=row["cluster_id"],
        title=row["title"],
        signature=row["signature"],
        matched_skill=row["matched_skill"],
        status=row["status"],
        first_seen_run_id=row["first_seen_run_id"],
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_seen_run_id=row["last_seen_run_id"],
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        ready_at=_dt_or_none(row["ready_at"]),
        promoted_at=_dt_or_none(row["promoted_at"]),
        promoted_artifact_paths=tuple(json.loads(row["promoted_artifact_paths_json"])),
        snooze_until_run=row["snooze_until_run"],
        dismiss_reason=row["dismiss_reason"],
        decided_by=row["decided_by"],
        decided_at=_dt_or_none(row["decided_at"]),
        current_evidence=json.loads(row["current_evidence_json"]),
    )


def _observation_from_row(row: sqlite3.Row) -> CandidateObservation:
    return CandidateObservation(
        candidate_id=row["candidate_id"],
        run_id=row["run_id"],
        observed_at=datetime.fromisoformat(row["observed_at"]),
        count=row["count"],
        n_users=row["n_users"],
        n_sessions=row["n_sessions"],
        total_cost_usd=row["total_cost_usd"],
        score=row["score"],
        signals=json.loads(row["signals_json"]),
        met_evidence_bar=bool(row["met_evidence_bar"]),
        crossed_threshold=bool(row["crossed_threshold"]),
    )


def _span_where(f: QueryFilters, alias: str = "") -> tuple[str, list]:
    """WHERE clause over span columns; ``alias`` qualifies them for joined queries."""
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list = []
    if f.project:
        clauses.append(f"{prefix}project = ?")
        params.append(f.project)
    if f.start:
        clauses.append(f"{prefix}start_time >= ?")
        params.append(_iso(f.start))
    if f.end:
        clauses.append(f"{prefix}start_time < ?")
        params.append(_iso(f.end))
    if f.span_kinds:
        clauses.append(f"{prefix}span_kind IN ({','.join(['?'] * len(f.span_kinds))})")
        params.extend(f.span_kinds)
    if f.workflow_stage:
        clauses.append(f"{prefix}workflow_stage = ?")
        params.append(f.workflow_stage)
    if f.asset_class:
        clauses.append(f"{prefix}asset_class = ?")
        params.append(f.asset_class)
    if f.model_name:
        clauses.append(f"{prefix}model_name = ?")
        params.append(f.model_name)
    if f.session_id:
        clauses.append(f"{prefix}session_id = ?")
        params.append(f.session_id)
    if f.user_id:
        clauses.append(f"{prefix}user_id = ?")
        params.append(f.user_id)
    if f.search:
        clauses.append(f"{prefix}input_text LIKE ?")
        params.append(f"%{f.search}%")
    if f.search_any:
        # OR within the group, AND with everything else: "must contain one of these".
        ors = " OR ".join(f"{prefix}input_text LIKE ?" for _ in f.search_any)
        clauses.append(f"({ors})")
        params.extend(f"%{term}%" for term in f.search_any)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params
