"""Local SQLite store. Single writer, idempotent inserts (span_id primary key)."""

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .models import (
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
"""


class Store:
    """Thin wrapper over sqlite3 — every method opens/uses one connection owned by the store."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

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

    # ---- internals -----------------------------------------------------------
    def _count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


_SNAPSHOT_COLUMNS = [
    "run_id", "cluster_id", "representative", "count", "n_users", "skill_name",
    "first_seen", "last_seen",
]


def _evaluation_row(evaluation: SpanEvaluation) -> tuple:
    return (
        evaluation.span_id, evaluation.name, evaluation.source, evaluation.label,
        evaluation.score, evaluation.explanation, evaluation.annotator_kind,
        evaluation.target, _iso(evaluation.created_at),
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
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params
