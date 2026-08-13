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


def _span_where(f: QueryFilters) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if f.project:
        clauses.append("project = ?")
        params.append(f.project)
    if f.start:
        clauses.append("start_time >= ?")
        params.append(_iso(f.start))
    if f.end:
        clauses.append("start_time < ?")
        params.append(_iso(f.end))
    if f.span_kinds:
        clauses.append(f"span_kind IN ({','.join(['?'] * len(f.span_kinds))})")
        params.extend(f.span_kinds)
    if f.workflow_stage:
        clauses.append("workflow_stage = ?")
        params.append(f.workflow_stage)
    if f.asset_class:
        clauses.append("asset_class = ?")
        params.append(f.asset_class)
    if f.model_name:
        clauses.append("model_name = ?")
        params.append(f.model_name)
    if f.session_id:
        clauses.append("session_id = ?")
        params.append(f.session_id)
    if f.user_id:
        clauses.append("user_id = ?")
        params.append(f.user_id)
    if f.search:
        clauses.append("input_text LIKE ?")
        params.append(f"%{f.search}%")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params
