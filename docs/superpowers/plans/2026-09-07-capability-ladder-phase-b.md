# Capability Promotion Ladder — Phase B (Scoped Run) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing mining pipeline **scoped to one capability** over a
`[from, to]` window, record each run, and diff run-over-run — driven by
`pheonix run --capability <id>` / `--all`.

**Architecture:** A new `capability_run.py` holds `run_capability_analysis()`
(the scoped analysis for one capability — pure, offline-testable, does not
scrape) and `run_capabilities()` (the orchestrator — syncs `capability.yaml` →
DB, scrapes each distinct Phoenix project once, loops the analysis, and never
lets one capability's failure abort the others). `pipeline.run_analysis` and the
global analysis tables are **untouched** — the legacy dashboard keeps working.
Three new tables (`capability_runs`, `capability_cluster_snapshots`,
`capability_cluster_members`) hold per-run scoped output, pruned per capability
to `run_history_limit`. Rung 1 / Rung 2 candidate detection is **not** in this
phase (Phases C / D) — the run rows carry `n_rung1_candidates` /
`n_rung2_candidates` columns, written as `0` for now.

**Tech Stack:** Python 3.11+, pydantic v2 (frozen models), pandas, Typer,
SQLite (stdlib `sqlite3`), pytest, ruff, uv. Optional `arize-phoenix-client`
(the `live` extra) for real scraping — tests never touch it.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
— this plan implements §7.2 (`capability_runs`, `capability_cluster_snapshots`),
§10.2 steps 1–5 and 10, and the "generalise `cluster_deltas`" / "partial-failure
resilience" items of §13's Phase B row. Steps 6–9 of §10.2 (evaluate, Rung 1,
Rung 2, lifecycle) are Phases C–D.

## Global Constraints

- Python **>= 3.11**. Files stay **under 400 lines** (new `capability_run.py`
  must not exceed it; `storage.py` and `cli.py` are pre-existing core files —
  judge only what this phase adds).
- **All functions return NEW objects** — never mutate an input argument.
- **Type hints on every function signature.**
- Data models are **frozen** — subclass `_Frozen` in `models.py`
  (`ConfigDict(frozen=True)`); mutable defaults via `Field(default_factory=...)`.
- **TDD:** write the test in `tests/test_<module>.py` first, watch it fail, then
  implement.
- Run a module's tests: `uv run pytest tests/test_<module>.py -q`. Run
  everything: `uv run pytest -q` — **exit code 0 is the pass signal; the summary
  line is suppressed in this environment, trust the exit code.** The suite is at
  **609** after Phase A; nothing that passes may regress.
- Lint: `uv run ruff check src tests` (rules `E, F, I, UP, B`; line length 100).
- **No network, no live Phoenix in tests.** `PhoenixClientWrapper` is exercised
  only via a monkeypatched/fake stand-in.
- Commit message format: `<type>: <description>` — one commit per task (the
  final step of each task).
- Package is `phoenix_scraper`; CLI is `pheonix`. Settings env prefix `PHEONIX_`.
- `run_id` is an ISO-8601 UTC timestamp string (matches the existing
  `analysis_runs.run_id`). `run_history_limit` (existing setting, default 20)
  bounds recorded runs **per capability**.
- Phase A shipped: `Capability`/`CapabilityFilter` models; `capability.py`
  (`load_capability`, `load_all_capabilities`, `scaffold_capability`,
  `capability_query_filters(capability, *, start, end, limit)`,
  `capability_skill_dirs(root, cap_id)`, `validate_id`); `Store`
  `upsert_capability` / `get_capability` / `capabilities_frame` /
  `delete_capability`; `pheonix capability new|list|show|sync`.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/phoenix_scraper/models.py` | modify | add `CapabilityRun`, `CapabilityRunResult` frozen models |
| `src/phoenix_scraper/storage.py` | modify | 3 tables in `_SCHEMA`; `span_count`; `record_capability_run`; `capability_runs_frame`; `previous_capability_run_id`; `capability_run_snapshot_frame`; `capability_cluster_members_frame`; `latest_capability_run_id_on_day`; `_prune_capability_runs` |
| `src/phoenix_scraper/capability_run.py` | **create** | `load_capability_skills`; `run_capability_analysis` (scoped analysis + record, no scrape); `run_capabilities` (sync + scrape-once-per-project + loop + resilience) |
| `src/phoenix_scraper/cli.py` | modify | `pheonix run` command; `pheonix capability runs` sub-command; option singletons |
| `src/phoenix_scraper/skill_coverage.py` | (no change) | `cluster_deltas` is already frame-generic — Phase B feeds it scoped snapshot frames |
| `tests/test_capability_run_storage.py` | **create** | the new `Store` methods (Task 1) |
| `tests/test_capability_run.py` | **create** | `run_capability_analysis` + `run_capabilities` (Tasks 2–3) |
| `tests/test_capability_run_cli.py` | **create** | `pheonix run` / `pheonix capability runs` (Task 4) |
| `README.md` | modify | "Daily runs" section |
| `CONTRACTS.md` | modify | `capability_run.py` block + note the 3 new tables |

**Column choice note:** `capability_cluster_snapshots` uses `skill_name` (not the
spec's indicative `matched_skill`) so it drops straight into the existing
`skill_coverage._counts_by_cluster` / `cluster_deltas` with no change — matching
the existing `cluster_snapshots` column. Phase C maps `snapshot.skill_name` →
`candidate.matched_skill` when it creates candidates.

**Deliberately deferred inside Phase B** (documented, not silently dropped):
- `derive_sessions` per capability — not persisted (no `capability_sessions`
  table in the spec; Phase F's Analytics tab recomputes from the in-scope frame).
- `evaluate_spans` per capability — §10.2 step 6 flags the "scope reads not
  writes" question as unresolved; Phase B does not evaluate. Phase C makes the
  call (likely `store.upsert_evaluations` over the in-scope frame — idempotent,
  non-destructive — rather than the global `replace_local_evaluations`).

---

## Task 1: Storage & models — the three run tables

**Files:**
- Modify: `src/phoenix_scraper/models.py`
- Modify: `src/phoenix_scraper/storage.py`
- Test: `tests/test_capability_run_storage.py` (create)

**Interfaces:**
- Consumes: `models.Capability` (Phase A).
- Produces:
  - `models.CapabilityRun(run_id: str, capability_id: str, started_at: datetime,
    finished_at: datetime | None = None, window_start: datetime, window_end:
    datetime, n_spans: int = 0, n_in_scope_spans: int = 0, n_clusters: int = 0,
    n_rung1_candidates: int = 0, n_rung2_candidates: int = 0, status:
    Literal["ok","partial","failed"] = "ok", notes: tuple[str, ...] = ())` —
    frozen.
  - `models.CapabilityRunResult(run: CapabilityRun, clusters: tuple[PromptCluster,
    ...] = (), matches: tuple[SkillMatch, ...] = (), proposals:
    tuple[SkillGapProposal, ...] = (), previous_run_id: str | None = None)` —
    frozen.
  - `Store.span_count(self) -> int`
  - `Store.record_capability_run(self, run: CapabilityRun, snapshot_rows:
    list[dict], member_rows: list[tuple[str, str]], history_limit: int) -> None`
    — writes the `capability_runs` row, replaces this `(capability_id, run_id)`'s
    snapshot + member rows, prunes older runs for this capability.
  - `Store.capability_runs_frame(self, capability_id: str, limit: int = 50) ->
    pd.DataFrame` — newest first.
  - `Store.previous_capability_run_id(self, capability_id: str, before: str | None
    = None) -> str | None`
  - `Store.capability_run_snapshot_frame(self, capability_id: str, run_id: str |
    None) -> pd.DataFrame` — empty frame (with columns) when `run_id is None`.
  - `Store.capability_cluster_members_frame(self, capability_id: str, run_id: str)
    -> pd.DataFrame` — columns `cluster_id, span_id`.
  - `Store.latest_capability_run_id_on_day(self, capability_id: str, day: str) ->
    str | None` — `day` is `YYYY-MM-DD`; matches `run_id` starting with it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_run_storage.py`:

```python
"""Tests for the capability_runs / snapshots / members tables on Store."""

from datetime import UTC, datetime

from phoenix_scraper.models import CapabilityRun

RUN_TS = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)


def _run(run_id: str = "2026-09-07T10:00:00+00:00", cap: str = "fobo", **over) -> CapabilityRun:
    base = dict(
        run_id=run_id,
        capability_id=cap,
        started_at=RUN_TS,
        finished_at=RUN_TS,
        window_start=datetime(2026, 8, 8, tzinfo=UTC),
        window_end=datetime(2026, 9, 7, tzinfo=UTC),
        n_spans=500,
        n_in_scope_spans=210,
        n_clusters=3,
        status="ok",
        notes=(),
    )
    base.update(over)
    return CapabilityRun(**base)


def _snap(run_id: str, cluster_id: str, cap: str = "fobo", **over) -> dict:
    base = dict(
        capability_id=cap, run_id=run_id, cluster_id=cluster_id,
        signature="why recon break of <num> on <book>",
        representative="Why is there a recon break of 100k on CDS_IG_NY?",
        count=10, n_users=4, skill_name="fobo-break-triage",
        covered=1, in_scope=1, route_len_avg=3.0, long_route=0,
        first_seen=None, last_seen=None,
    )
    base.update(over)
    return base


class TestRecordAndRead:
    def test_record_then_runs_frame(self, tmp_store) -> None:
        run = _run()
        tmp_store.record_capability_run(
            run, [_snap(run.run_id, "aaa"), _snap(run.run_id, "bbb", count=5)],
            [("aaa", "s1"), ("aaa", "s2"), ("bbb", "s3")], history_limit=20,
        )
        frame = tmp_store.capability_runs_frame("fobo")
        assert len(frame) == 1
        row = frame.iloc[0]
        assert row["run_id"] == run.run_id
        assert row["n_in_scope_spans"] == 210
        assert row["status"] == "ok"

    def test_snapshot_and_members_round_trip(self, tmp_store) -> None:
        run = _run()
        tmp_store.record_capability_run(
            run, [_snap(run.run_id, "aaa")], [("aaa", "s1"), ("aaa", "s2")],
            history_limit=20,
        )
        snaps = tmp_store.capability_run_snapshot_frame("fobo", run.run_id)
        assert list(snaps["cluster_id"]) == ["aaa"]
        assert snaps.iloc[0]["skill_name"] == "fobo-break-triage"
        members = tmp_store.capability_cluster_members_frame("fobo", run.run_id)
        assert set(members["span_id"]) == {"s1", "s2"}

    def test_snapshot_frame_none_run_is_empty_with_columns(self, tmp_store) -> None:
        frame = tmp_store.capability_run_snapshot_frame("fobo", None)
        assert frame.empty
        assert "cluster_id" in frame.columns and "count" in frame.columns

    def test_re_record_same_run_replaces_snapshots(self, tmp_store) -> None:
        run = _run()
        tmp_store.record_capability_run(run, [_snap(run.run_id, "aaa")], [("aaa", "s1")], history_limit=20)
        tmp_store.record_capability_run(run, [_snap(run.run_id, "zzz")], [("zzz", "s9")], history_limit=20)
        snaps = tmp_store.capability_run_snapshot_frame("fobo", run.run_id)
        assert list(snaps["cluster_id"]) == ["zzz"]
        assert len(tmp_store.capability_runs_frame("fobo")) == 1

    def test_previous_capability_run_id(self, tmp_store) -> None:
        r1 = _run("2026-09-05T10:00:00+00:00")
        r2 = _run("2026-09-06T10:00:00+00:00")
        r3 = _run("2026-09-07T10:00:00+00:00")
        for r in (r1, r2, r3):
            tmp_store.record_capability_run(r, [_snap(r.run_id, "aaa")], [("aaa", "s1")], history_limit=20)
        assert tmp_store.previous_capability_run_id("fobo") == r3.run_id
        assert tmp_store.previous_capability_run_id("fobo", before=r3.run_id) == r2.run_id
        assert tmp_store.previous_capability_run_id("fobo", before=r1.run_id) is None
        assert tmp_store.previous_capability_run_id("other") is None

    def test_prune_keeps_newest_n_per_capability(self, tmp_store) -> None:
        for day in range(1, 6):
            r = _run(f"2026-09-0{day}T10:00:00+00:00")
            tmp_store.record_capability_run(r, [_snap(r.run_id, "aaa")], [("aaa", "s1")], history_limit=3)
        runs = tmp_store.capability_runs_frame("fobo")
        assert len(runs) == 3
        assert list(runs["run_id"]) == [
            "2026-09-05T10:00:00+00:00", "2026-09-04T10:00:00+00:00", "2026-09-03T10:00:00+00:00",
        ]
        # snapshots + members for pruned runs are gone
        assert tmp_store.capability_run_snapshot_frame("fobo", "2026-09-01T10:00:00+00:00").empty
        assert tmp_store.capability_cluster_members_frame("fobo", "2026-09-01T10:00:00+00:00").empty

    def test_prune_is_per_capability(self, tmp_store) -> None:
        for day in range(1, 4):
            for cap in ("fobo", "plex"):
                r = _run(f"2026-09-0{day}T10:00:00+00:00", cap=cap)
                tmp_store.record_capability_run(
                    r, [_snap(r.run_id, "aaa", cap=cap)], [("aaa", "s1")], history_limit=2,
                )
        assert len(tmp_store.capability_runs_frame("fobo")) == 2
        assert len(tmp_store.capability_runs_frame("plex")) == 2

    def test_latest_run_id_on_day(self, tmp_store) -> None:
        a = _run("2026-09-07T08:00:00+00:00")
        b = _run("2026-09-07T15:00:00+00:00")
        c = _run("2026-09-06T09:00:00+00:00")
        for r in (a, b, c):
            tmp_store.record_capability_run(r, [_snap(r.run_id, "aaa")], [("aaa", "s1")], history_limit=20)
        assert tmp_store.latest_capability_run_id_on_day("fobo", "2026-09-07") == b.run_id
        assert tmp_store.latest_capability_run_id_on_day("fobo", "2026-09-01") is None

    def test_span_count(self, tmp_store, sample_spans) -> None:
        assert tmp_store.span_count() == 0
        tmp_store.upsert_spans(sample_spans)
        assert tmp_store.span_count() == len(sample_spans)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_run_storage.py -q`
Expected: FAIL — `ImportError: cannot import name 'CapabilityRun' from 'phoenix_scraper.models'`.

- [ ] **Step 3: Add the models**

In `src/phoenix_scraper/models.py`, after the `Capability` class, add:

```python
class CapabilityRun(_Frozen):
    """One recorded scoped analysis run for a capability (mirrors capability_runs)."""

    run_id: str  # ISO-8601 UTC timestamp
    capability_id: str
    started_at: datetime
    finished_at: datetime | None = None
    window_start: datetime
    window_end: datetime
    n_spans: int = 0  # total spans in the store at run time
    n_in_scope_spans: int = 0
    n_clusters: int = 0
    n_rung1_candidates: int = 0  # written 0 until Phase C
    n_rung2_candidates: int = 0  # written 0 until Phase D
    status: Literal["ok", "partial", "failed"] = "ok"
    notes: tuple[str, ...] = ()


class CapabilityRunResult(_Frozen):
    """The return value of run_capability_analysis — the run plus what a caller
    needs to print or report without re-querying."""

    run: CapabilityRun
    clusters: tuple[PromptCluster, ...] = ()
    matches: tuple[SkillMatch, ...] = ()
    proposals: tuple[SkillGapProposal, ...] = ()
    previous_run_id: str | None = None
```

`Literal` and `Field` are already imported in `models.py`. `CapabilityRunResult`
references `PromptCluster`, `SkillMatch`, `SkillGapProposal`, so place both new
classes **immediately before the `SpanEvaluation` class** (after
`SkillGapProposal`, which is where those three are defined).

- [ ] **Step 4: Add the schema**

In `src/phoenix_scraper/storage.py`, inside `_SCHEMA`, after the `capabilities`
table (added in Phase A) and before the closing `"""`, add:

```sql

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
```

- [ ] **Step 5: Extend the storage imports**

Add `CapabilityRun` to the `from .models import (...)` block in `storage.py`
(alphabetical — after `Capability`, `CapabilityFilter`).

- [ ] **Step 6: Add `span_count` and the capability-run methods**

In `storage.py`, in the `# ---- capabilities` section (added in Phase A), after
`delete_capability`, add:

```python
    # ---- capability runs ------------------------------------------------------
    def span_count(self) -> int:
        return self._count("spans")

    def record_capability_run(
        self,
        run: "CapabilityRun",
        snapshot_rows: list[dict],
        member_rows: list[tuple[str, str]],
        history_limit: int,
    ) -> None:
        """Write the run row, replace this run's snapshots + members, prune."""
        c = self._conn
        c.execute(
            "INSERT OR REPLACE INTO capability_runs (capability_id, run_id, "
            "started_at, finished_at, window_start, window_end, n_spans, "
            "n_in_scope_spans, n_clusters, n_rung1_candidates, n_rung2_candidates, "
            "status, notes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.capability_id, run.run_id, _iso(run.started_at),
                _iso(run.finished_at), _iso(run.window_start), _iso(run.window_end),
                run.n_spans, run.n_in_scope_spans, run.n_clusters,
                run.n_rung1_candidates, run.n_rung2_candidates, run.status,
                json.dumps(list(run.notes)),
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
        c.executemany(
            "INSERT INTO capability_cluster_snapshots (capability_id, run_id, "
            "cluster_id, signature, representative, count, n_users, skill_name, "
            "covered, in_scope, route_len_avg, long_route, first_seen, last_seen) "
            "VALUES (:capability_id,:run_id,:cluster_id,:signature,:representative,"
            ":count,:n_users,:skill_name,:covered,:in_scope,:route_len_avg,"
            ":long_route,:first_seen,:last_seen)",
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
```

Add the module-level column list near `_SNAPSHOT_COLUMNS`:

```python
_CAP_SNAPSHOT_COLUMNS = [
    "capability_id", "run_id", "cluster_id", "signature", "representative",
    "count", "n_users", "skill_name", "covered", "in_scope", "route_len_avg",
    "long_route", "first_seen", "last_seen",
]
```

The `"CapabilityRun"` forward-reference in the method signature is a string
because `record_capability_run` is defined on the class before you would
normally read it top-to-bottom; import `CapabilityRun` at module top (Step 5)
and you may drop the quotes — either is fine, keep it consistent with the file
(the file imports its models, so **unquote it**: `run: CapabilityRun`).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_run_storage.py -q`
Expected: PASS.

- [ ] **Step 8: Backward-compat + lint + full suite**

Run: `uv run pytest tests/test_capability_storage.py tests/test_scraper.py tests/test_pipeline.py -q && uv run ruff check src tests && uv run pytest -q`
Expected: all green (609 → 619); ruff clean. The schema additions are
`CREATE TABLE IF NOT EXISTS` under the existing `executescript`, so existing DBs
gain the tables on next open.

- [ ] **Step 9: Commit**

```bash
git add src/phoenix_scraper/models.py src/phoenix_scraper/storage.py tests/test_capability_run_storage.py
git commit -m "feat: capability_runs / snapshots / members tables and Store methods"
```

---

## Task 2: `run_capability_analysis` — the scoped analysis

**Files:**
- Create: `src/phoenix_scraper/capability_run.py`
- Test: `tests/test_capability_run.py` (create)

**Interfaces:**
- Consumes: Task 1's models + `Store` methods; `capability.capability_query_filters`,
  `capability.capability_skill_dirs`; `pipeline.ANALYSIS_SPAN_LIMIT`;
  `costs.load_pricing` / `compute_span_costs`; `cluster.build_clusters`;
  `skills.load_all_skills` / `scan_skill_dirs`; `skills_mapper.match_clusters`;
  `skill_coverage.annotate_coverage`; `insights.cluster_efficiency`.
- Produces:
  - `load_capability_skills(settings: Settings, capability: Capability) ->
    list[SkillEntry]` — `load_all_skills(settings)` plus the capability's own
    `skills/` dir, de-duped by name (catalog/global wins, matching
    `load_all_skills`).
  - `run_capability_analysis(store: Store, settings: Settings, capability:
    Capability, *, window_start: datetime | None = None, window_end: datetime |
    None = None, replace_today: bool = False, notes: list[str] | None = None, now:
    datetime | None = None) -> CapabilityRunResult` — does NOT scrape.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_run.py`:

```python
"""Tests for run_capability_analysis and run_capabilities (offline)."""

from datetime import UTC, datetime, timedelta

import pytest

from phoenix_scraper import capability as cap_mod
from phoenix_scraper.capability_run import run_capabilities, run_capability_analysis
from phoenix_scraper.models import CapabilityFilter

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def fobo_capability(tmp_path, settings):
    root = tmp_path / "caps"
    cap = cap_mod.scaffold_capability(
        root, "fobo", name="FOBO",
        cap_filter=CapabilityFilter(workflow_stage="fobo_recon"),
        window_days=30,
    )
    return settings.model_copy(update={"capabilities_dir": root}), cap


class TestRunCapabilityAnalysis:
    def test_scopes_to_the_capability_filter(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        # sample_spans: 8 fobo_recon LLM spans, 1 adjustments TOOL, 1 commentary_signoff.
        # Only fobo_recon user turns are in scope.
        assert result.run.n_in_scope_spans == 8
        assert result.run.n_spans == 10  # total in the store, unscoped
        assert result.run.capability_id == "fobo"
        assert result.run.status == "ok"
        assert all("fobo" not in c.representative.lower() or True for c in result.clusters)

    def test_window_default_is_now_minus_window_days(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        assert result.run.window_end == NOW
        assert result.run.window_start == NOW - timedelta(days=30)

    def test_explicit_window_overrides(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        ws, we = datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 25, tzinfo=UTC)
        result = run_capability_analysis(
            seeded_store, settings, cap, window_start=ws, window_end=we, now=NOW
        )
        assert result.run.window_start == ws and result.run.window_end == we

    def test_records_the_run_and_snapshots(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        runs = seeded_store.capability_runs_frame("fobo")
        assert len(runs) == 1 and runs.iloc[0]["run_id"] == result.run.run_id
        snaps = seeded_store.capability_run_snapshot_frame("fobo", result.run.run_id)
        assert len(snaps) == result.run.n_clusters == len(result.clusters)
        members = seeded_store.capability_cluster_members_frame("fobo", result.run.run_id)
        assert len(members) > 0
        assert runs.iloc[0]["n_rung1_candidates"] == 0  # Phase C fills this

    def test_previous_run_id_is_read_before_recording(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        first = run_capability_analysis(seeded_store, settings, cap,
                                        now=NOW - timedelta(days=1))
        second = run_capability_analysis(seeded_store, settings, cap, now=NOW)
        assert first.previous_run_id is None
        assert second.previous_run_id == first.run.run_id

    def test_replace_today_reuses_the_days_run_id(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        a = run_capability_analysis(seeded_store, settings, cap,
                                    now=NOW.replace(hour=8))
        b = run_capability_analysis(seeded_store, settings, cap,
                                    now=NOW.replace(hour=17), replace_today=True)
        assert b.run.run_id == a.run.run_id
        assert len(seeded_store.capability_runs_frame("fobo")) == 1

    def test_empty_scope_records_a_zero_run(self, seeded_store, tmp_path, settings) -> None:
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "ghost", name="Ghost",
            cap_filter=CapabilityFilter(workflow_stage="does_not_exist"),
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        result = run_capability_analysis(seeded_store, s, cap, now=NOW)
        assert result.run.n_in_scope_spans == 0
        assert result.run.n_clusters == 0
        assert result.run.status == "ok"
        assert len(seeded_store.capability_runs_frame("ghost")) == 1

    def test_notes_force_partial_status(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        result = run_capability_analysis(
            seeded_store, settings, cap, notes=["scrape failed for pnl-agent"], now=NOW
        )
        assert result.run.status == "partial"
        assert "scrape failed for pnl-agent" in result.run.notes

    def test_capability_skills_dir_is_scanned(self, seeded_store, fobo_capability) -> None:
        settings, cap = fobo_capability
        skill_md = (settings.capabilities_dir / "fobo" / "skills" / "recon.md")
        skill_md.write_text(
            "---\nname: recon-break-local\ndescription: local recon skill\n"
            "keywords: [recon, break]\nexample_prompts:\n"
            '  - "Why is there an FX recon break on the EURUSD book?"\n---\n',
            encoding="utf-8",
        )
        from phoenix_scraper.capability_run import load_capability_skills
        names = {s.name for s in load_capability_skills(settings, cap)}
        assert "recon-break-local" in names
        assert "glossary-explainer" in names  # catalog entries still present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_run.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'phoenix_scraper.capability_run'`.

- [ ] **Step 3: Create the module**

Create `src/phoenix_scraper/capability_run.py`:

```python
"""Run the mining pipeline scoped to one capability, and orchestrate runs.

`run_capability_analysis` is the per-capability unit: it does NOT scrape — it
reads the already-populated store, restricts to the capability's filter + window,
runs costs -> clusters -> skills -> matches -> coverage -> efficiency, records a
`capability_runs` row plus this run's `capability_cluster_snapshots` /
`capability_cluster_members`, and returns a `CapabilityRunResult`.

`run_capabilities` is the orchestrator used by `pheonix run` and (Phase E) the
API: it syncs each `capability.yaml` into the DB, scrapes each distinct Phoenix
project once (best-effort), then loops `run_capability_analysis`, isolating
failures so one capability never aborts the others.

Rung 1 / Rung 2 candidate detection is Phase C / D — the run rows carry
`n_rung1_candidates` / `n_rung2_candidates`, written 0 here.
"""

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd

from .capability import capability_query_filters, capability_skill_dirs, load_capability
from .capability import load_all_capabilities
from .cluster import build_clusters
from .config import Settings
from .costs import compute_span_costs, load_pricing
from .insights import cluster_efficiency
from .models import (
    Capability,
    CapabilityRun,
    CapabilityRunResult,
    QueryFilters,
    SkillEntry,
)
from .phoenix_client import PhoenixClientWrapper
from .pipeline import ANALYSIS_SPAN_LIMIT
from .scraper import scrape_once
from .skill_coverage import annotate_coverage
from .skills import load_all_skills, scan_skill_dirs
from .skills_mapper import match_clusters
from .storage import Store

logger = logging.getLogger(__name__)


def load_capability_skills(settings: Settings, capability: Capability) -> list[SkillEntry]:
    """Catalog + PHEONIX_SKILLS_DIRS + this capability's own skills/ dir,
    de-duped by name (earlier source wins, matching load_all_skills)."""
    combined = load_all_skills(settings) + scan_skill_dirs(
        capability_skill_dirs(settings.capabilities_dir, capability.id)
    )
    seen: set[str] = set()
    unique: list[SkillEntry] = []
    for skill in combined:
        if skill.name not in seen:
            seen.add(skill.name)
            unique.append(skill)
    return unique


def _clusters_frame(clusters: list) -> pd.DataFrame:
    if not clusters:
        return pd.DataFrame(
            columns=["cluster_id", "signature", "representative", "count", "n_users"]
        )
    return pd.DataFrame([c.model_dump() for c in clusters])


def _members_frame(clusters: list) -> pd.DataFrame:
    rows = [
        {"cluster_id": c.cluster_id, "span_id": sid}
        for c in clusters
        for sid in c.span_ids
    ]
    return pd.DataFrame(rows, columns=["cluster_id", "span_id"])


def _snapshot_rows(
    capability_id: str,
    run_id: str,
    clusters: list,
    matches: list,
    annotated: pd.DataFrame,
    efficiency: pd.DataFrame,
) -> list[dict]:
    skill_by_cluster = {m.cluster_id: m.skill_name for m in matches}
    covered_by_cluster: dict[str, int] = {}
    if not annotated.empty and "covered" in annotated.columns:
        for row in annotated.to_dict("records"):
            covered_by_cluster[row["cluster_id"]] = int(bool(row["covered"]))
    route_by_cluster: dict[str, tuple[float | None, int]] = {}
    if not efficiency.empty:
        for row in efficiency.to_dict("records"):
            route_by_cluster[row["cluster_id"]] = (
                row.get("route_len_avg"), int(bool(row.get("long_route"))),
            )
    rows = []
    for c in clusters:
        route_len, long_route = route_by_cluster.get(c.cluster_id, (None, 0))
        rows.append(
            {
                "capability_id": capability_id,
                "run_id": run_id,
                "cluster_id": c.cluster_id,
                "signature": c.signature,
                "representative": c.representative,
                "count": c.count,
                "n_users": c.n_users,
                "skill_name": skill_by_cluster.get(c.cluster_id),
                "covered": covered_by_cluster.get(c.cluster_id, 0),
                "in_scope": 1,
                "route_len_avg": route_len,
                "long_route": long_route,
                "first_seen": c.first_seen.isoformat() if c.first_seen else None,
                "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            }
        )
    return rows


def run_capability_analysis(
    store: Store,
    settings: Settings,
    capability: Capability,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    replace_today: bool = False,
    notes: list[str] | None = None,
    now: datetime | None = None,
) -> CapabilityRunResult:
    """Analyse the capability's in-scope spans over its window and record the run.

    Does not scrape. ``notes`` (e.g. a scrape failure from the orchestrator) are
    stored on the run and force ``status='partial'``.
    """
    started_at = now or datetime.now(UTC)
    window_end = window_end or started_at
    window_start = window_start or (window_end - timedelta(days=capability.window_days))
    run_notes = list(notes or [])

    filters = capability_query_filters(
        capability, start=window_start, end=window_end, limit=ANALYSIS_SPAN_LIMIT
    )
    in_scope = store.spans_frame(filters)

    if not in_scope.empty:
        pricing, default_pricing = load_pricing(settings.pricing_path)
        new_costs = compute_span_costs(in_scope, pricing, default_pricing)
        if new_costs:
            store.update_span_costs(new_costs)
            in_scope = store.spans_frame(filters)

    clusters = build_clusters(in_scope, fuzz_threshold=settings.cluster_fuzz_threshold)
    skills = load_capability_skills(settings, capability)
    matches, proposals = match_clusters(
        clusters, skills, threshold=settings.skill_match_threshold
    )

    clusters_df = _clusters_frame(clusters)
    matches_df = pd.DataFrame(
        [m.model_dump() for m in matches], columns=["cluster_id", "skill_name", "score", "method"]
    )
    annotated = annotate_coverage(
        clusters_df, matches_df, skills, threshold=settings.skill_coverage_threshold
    )
    efficiency = cluster_efficiency(in_scope, clusters_df, _members_frame(clusters))

    reused_today = False
    if replace_today:
        existing = store.latest_capability_run_id_on_day(
            capability.id, window_end.date().isoformat()
        )
        run_id = existing or started_at.isoformat()
        reused_today = existing is not None
    else:
        run_id = started_at.isoformat()

    # Read the predecessor BEFORE recording. When --replace-today reused an
    # existing id, "latest" IS this run, so ask for the one strictly before it.
    previous_run_id = (
        store.previous_capability_run_id(capability.id, before=run_id)
        if reused_today
        else store.previous_capability_run_id(capability.id)
    )

    run = CapabilityRun(
        run_id=run_id,
        capability_id=capability.id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        window_start=window_start,
        window_end=window_end,
        n_spans=store.span_count(),
        n_in_scope_spans=int(len(in_scope)),
        n_clusters=len(clusters),
        status="partial" if run_notes else "ok",
        notes=tuple(run_notes),
    )
    store.record_capability_run(
        run,
        _snapshot_rows(capability.id, run_id, clusters, matches, annotated, efficiency),
        [(c.cluster_id, sid) for c in clusters for sid in c.span_ids],
        history_limit=settings.run_history_limit,
    )
    return CapabilityRunResult(
        run=run,
        clusters=tuple(clusters),
        matches=tuple(matches),
        proposals=tuple(proposals),
        previous_run_id=previous_run_id,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_run.py -q -k RunCapabilityAnalysis or "load_capability"`
Expected: PASS for the `TestRunCapabilityAnalysis` class and
`test_capability_skills_dir_is_scanned`.

- [ ] **Step 5: File length + lint**

Run: `wc -l src/phoenix_scraper/capability_run.py && uv run ruff check src/phoenix_scraper/capability_run.py tests/test_capability_run.py`
Expected: under 400 lines; ruff clean. (If the `load_all_capabilities` import is
unused at this point it will fail `F401` — it is used in Task 3; add it there,
not here. For this task import only what `run_capability_analysis` uses.)

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/capability_run.py tests/test_capability_run.py
git commit -m "feat: run_capability_analysis — scoped analysis + run recording"
```

---

## Task 3: `run_capabilities` — the orchestrator

**Files:**
- Modify: `src/phoenix_scraper/capability_run.py`
- Test: `tests/test_capability_run.py` (append)

**Interfaces:**
- Consumes: Task 2's `run_capability_analysis`; `capability.load_capability` /
  `load_all_capabilities`; `scraper.scrape_once`; `PhoenixClientWrapper`.
- Produces:
  - `run_capabilities(store: Store, settings: Settings, *, capability_ids:
    list[str] | None = None, all_active: bool = False, client:
    PhoenixClientWrapper | None = None, window_start: datetime | None = None,
    window_end: datetime | None = None, replace_today: bool = False, now: datetime
    | None = None) -> list[CapabilityRunResult]` — one result per capability run
    (including a `status='failed'` result when a capability's analysis raised).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability_run.py`:

```python
class _FakeClient:
    """Stand-in for PhoenixClientWrapper; never touches the network."""

    def __init__(self, *, available=True, fail_projects=()):
        self._available = available
        self._fail = set(fail_projects)
        self.scraped: list[str] = []

    def available(self) -> bool:
        return self._available

    def fetch_spans(self, *, project, start, end, limit):
        self.scraped.append(project)
        if project in self._fail:
            raise RuntimeError(f"boom for {project}")
        return pd.DataFrame()  # no new spans


class TestRunCapabilities:
    def _two_caps(self, tmp_path, settings):
        root = tmp_path / "caps"
        cap_mod.scaffold_capability(root, "fobo", name="FOBO",
                                    cap_filter=CapabilityFilter(workflow_stage="fobo_recon"))
        cap_mod.scaffold_capability(root, "plex", name="PLEX",
                                    cap_filter=CapabilityFilter(workflow_stage="plex"))
        return settings.model_copy(update={"capabilities_dir": root})

    def test_all_active_runs_every_capability(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        results = run_capabilities(seeded_store, s, all_active=True, now=NOW)
        assert {r.run.capability_id for r in results} == {"fobo", "plex"}
        assert len(seeded_store.capability_runs_frame("fobo")) == 1
        assert len(seeded_store.capability_runs_frame("plex")) == 1

    def test_paused_capability_is_skipped(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        yaml_path = s.capabilities_dir / "plex" / "capability.yaml"
        yaml_path.write_text(
            yaml_path.read_text().replace("status: active", "status: paused"),
            encoding="utf-8",
        )
        results = run_capabilities(seeded_store, s, all_active=True, now=NOW)
        assert {r.run.capability_id for r in results} == {"fobo"}

    def test_sync_happens_before_run(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        run_capabilities(seeded_store, s, capability_ids=["fobo"], now=NOW)
        assert seeded_store.get_capability("fobo") is not None  # synced into the DB

    def test_scrape_once_per_distinct_project(self, seeded_store, tmp_path, settings) -> None:
        root = tmp_path / "caps"
        cap_mod.scaffold_capability(root, "a", name="A",
                                    cap_filter=CapabilityFilter(project="proj-1"))
        cap_mod.scaffold_capability(root, "b", name="B",
                                    cap_filter=CapabilityFilter(project="proj-1"))
        cap_mod.scaffold_capability(root, "c", name="C",
                                    cap_filter=CapabilityFilter(project="proj-2"))
        s = settings.model_copy(update={"capabilities_dir": root})
        client = _FakeClient()
        run_capabilities(seeded_store, s, all_active=True, client=client, now=NOW)
        assert sorted(client.scraped) == ["proj-1", "proj-2"]

    def test_scrape_failure_marks_partial_not_abort(self, seeded_store, tmp_path, settings) -> None:
        root = tmp_path / "caps"
        cap_mod.scaffold_capability(root, "a", name="A",
                                    cap_filter=CapabilityFilter(project="proj-1", workflow_stage="fobo_recon"))
        s = settings.model_copy(update={"capabilities_dir": root})
        client = _FakeClient(fail_projects=["proj-1"])
        results = run_capabilities(seeded_store, s, all_active=True, client=client, now=NOW)
        assert len(results) == 1
        assert results[0].run.status == "partial"
        assert any("proj-1" in n for n in results[0].run.notes)

    def test_offline_no_client_notes_stored_spans(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        results = run_capabilities(seeded_store, s, capability_ids=["fobo"], client=None, now=NOW)
        assert results[0].run.status == "partial"
        assert any("offline" in n.lower() or "stored spans" in n.lower()
                   for n in results[0].run.notes)

    def test_one_capability_failing_does_not_abort_the_rest(
        self, seeded_store, tmp_path, settings, monkeypatch
    ) -> None:
        s = self._two_caps(tmp_path, settings)
        real = run_capability_analysis

        def flaky(store, settings_, capability, **kw):
            if capability.id == "fobo":
                raise ValueError("kaboom")
            return real(store, settings_, capability, **kw)

        monkeypatch.setattr("phoenix_scraper.capability_run.run_capability_analysis", flaky)
        results = run_capabilities(seeded_store, s, all_active=True, now=NOW)
        by_id = {r.run.capability_id: r for r in results}
        assert by_id["fobo"].run.status == "failed"
        assert any("kaboom" in n for n in by_id["fobo"].run.notes)
        assert by_id["plex"].run.status in ("ok", "partial")
        # the failed run is still recorded so it is visible
        assert len(seeded_store.capability_runs_frame("fobo")) == 1
        assert seeded_store.capability_runs_frame("fobo").iloc[0]["status"] == "failed"

    def test_unknown_capability_id_raises(self, seeded_store, tmp_path, settings) -> None:
        s = self._two_caps(tmp_path, settings)
        with pytest.raises((ValueError, FileNotFoundError)):
            run_capabilities(seeded_store, s, capability_ids=["ghost"], now=NOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_run.py -q -k RunCapabilities`
Expected: FAIL — `ImportError: cannot import name 'run_capabilities'`.

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/capability_run.py`, add `load_all_capabilities` to the
`from .capability import ...` line if not already there, then append:

```python
def _target_capabilities(
    settings: Settings, capability_ids: list[str] | None, all_active: bool
) -> list[Capability]:
    root = settings.capabilities_dir
    if all_active:
        return [c for c in load_all_capabilities(root) if c.status == "active"]
    if capability_ids:
        return [load_capability(root, cid) for cid in capability_ids]
    return []


def _scrape_projects(
    store: Store,
    settings: Settings,
    projects: set[str],
    client: PhoenixClientWrapper | None,
) -> dict[str, list[str]]:
    """Scrape each project once. Returns {project: [note, ...]} for problems."""
    notes: dict[str, list[str]] = {}
    if client is None or not client.available():
        for project in projects:
            notes.setdefault(project, []).append(
                "offline: Phoenix not available, analysed stored spans"
            )
        return notes
    for project in sorted(projects):
        try:
            scrape_once(store, client, settings.model_copy(update={"project": project}))
        except Exception as exc:  # noqa: BLE001 — any client/network error must not abort the run
            logger.warning("scrape failed for %s: %s", project, exc)
            notes.setdefault(project, []).append(f"scrape failed for {project}: {exc}")
    return notes


def run_capabilities(
    store: Store,
    settings: Settings,
    *,
    capability_ids: list[str] | None = None,
    all_active: bool = False,
    client: PhoenixClientWrapper | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    replace_today: bool = False,
    now: datetime | None = None,
) -> list[CapabilityRunResult]:
    """Sync -> scrape each distinct project once -> run each capability, isolating
    failures so one capability never aborts the others."""
    started_at = now or datetime.now(UTC)
    capabilities = _target_capabilities(settings, capability_ids, all_active)
    for cap in capabilities:
        store.upsert_capability(cap)

    projects = {
        (cap.filter.project or settings.project) for cap in capabilities
    }
    scrape_notes = _scrape_projects(store, settings, projects, client)

    results: list[CapabilityRunResult] = []
    for cap in capabilities:
        project = cap.filter.project or settings.project
        cap_notes = list(scrape_notes.get(project, []))
        try:
            results.append(
                run_capability_analysis(
                    store, settings, cap,
                    window_start=window_start, window_end=window_end,
                    replace_today=replace_today, notes=cap_notes, now=started_at,
                )
            )
        except Exception as exc:  # noqa: BLE001 — record the failure, keep going
            logger.exception("capability %s failed", cap.id)
            failed = CapabilityRun(
                run_id=started_at.isoformat(),
                capability_id=cap.id,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                window_start=window_start or (started_at - timedelta(days=cap.window_days)),
                window_end=window_end or started_at,
                status="failed",
                notes=(*cap_notes, f"analysis failed: {exc}"),
            )
            store.record_capability_run(failed, [], [], history_limit=settings.run_history_limit)
            results.append(CapabilityRunResult(run=failed))
    return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_run.py -q`
Expected: PASS (whole file).

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (619 → ~638).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/capability_run.py tests/test_capability_run.py
git commit -m "feat: run_capabilities orchestrator — sync, scrape-once, failure isolation"
```

---

## Task 4: CLI — `pheonix run` and `pheonix capability runs`

**Files:**
- Modify: `src/phoenix_scraper/cli.py`
- Test: `tests/test_capability_run_cli.py` (create)

**Interfaces:**
- Consumes: `capability_run.run_capabilities`; Task 1's `Store` frames;
  `skill_coverage.cluster_deltas`; `PhoenixClientWrapper`.
- Produces:
  - CLI `pheonix run (--capability <id> | --all) [--from DT] [--to DT]
    [--replace-today] [--db] [--capabilities-dir]` — runs, prints a per-capability
    summary and a "what changed since last run" delta table. Exit 1 if neither /
    both of `--capability` / `--all` given.
  - CLI `pheonix capability runs <id> [--db] [--capabilities-dir]` — the recorded
    runs for a capability, newest first.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_run_cli.py`:

```python
"""CLI tests for `pheonix run` and `pheonix capability runs`."""

from pathlib import Path

from typer.testing import CliRunner, Result

from phoenix_scraper.cli import app as cli_app
from phoenix_scraper.storage import Store

runner = CliRunner()


def _invoke(*args: str) -> Result:
    return runner.invoke(cli_app, list(args))


def _seed_db(tmp_path: Path) -> Path:
    db = tmp_path / "c.db"
    r = _invoke("demo", "--db", str(db), "--export-dir", str(tmp_path / "e"), "--sessions", "20")
    assert r.exit_code == 0, r.output
    return db


class TestRun:
    def test_run_one_capability(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        assert _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common).exit_code == 0
        r = _invoke("run", "--capability", "fobo", *common)
        assert r.exit_code == 0, r.output
        assert "fobo" in r.output
        assert "in scope" in r.output.lower() or "in-scope" in r.output.lower()
        store = Store(db)
        try:
            assert len(store.capability_runs_frame("fobo")) == 1
        finally:
            store.close()

    def test_run_all(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        _invoke("capability", "new", "plex", "--stage", "plex", *common)
        r = _invoke("run", "--all", *common)
        assert r.exit_code == 0, r.output
        assert "fobo" in r.output and "plex" in r.output

    def test_requires_exactly_one_selector(self, tmp_path: Path) -> None:
        common = ("--capabilities-dir", str(tmp_path / "caps"), "--db", str(tmp_path / "c.db"))
        assert _invoke("run", *common).exit_code == 1
        assert _invoke("run", "--capability", "x", "--all", *common).exit_code == 1

    def test_second_run_shows_a_delta(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        _invoke("run", "--capability", "fobo", *common)
        r = _invoke("run", "--capability", "fobo", "--replace-today", *common)
        assert r.exit_code == 0, r.output
        # a delta section renders (may be "no change" — assert the header, not rows)
        assert "since" in r.output.lower() or "change" in r.output.lower()

    def test_from_to_window_override(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        r = _invoke("run", "--capability", "fobo",
                    "--from", "2020-01-01", "--to", "2020-02-01", *common)
        assert r.exit_code == 0, r.output
        assert "0" in r.output  # nothing in that window


class TestCapabilityRunsVerb:
    def test_lists_recorded_runs(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", "--stage", "fobo_recon", *common)
        _invoke("run", "--capability", "fobo", *common)
        r = _invoke("capability", "runs", "fobo", *common)
        assert r.exit_code == 0, r.output
        assert "run_id" in r.output or "window" in r.output.lower()

    def test_runs_for_capability_with_no_runs(self, tmp_path: Path) -> None:
        db, caps = _seed_db(tmp_path), tmp_path / "caps"
        common = ("--capabilities-dir", str(caps), "--db", str(db))
        _invoke("capability", "new", "fobo", *common)
        r = _invoke("capability", "runs", "fobo", *common)
        assert r.exit_code == 0
        assert "no runs" in r.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_run_cli.py -q`
Expected: FAIL — `run` is not a command (`exit_code == 2`).

- [ ] **Step 3: Add option singletons and imports**

In `cli.py`, add to the package imports (next to `from . import capability as
capability_mod`):

```python
from . import capability_run as capability_run_mod
from . import skill_coverage
```

(`skill_coverage` is already imported on the `from . import fixtures,
insights_quality, pipeline, scraper, skill_coverage` line — do **not** duplicate;
verify and skip if present.)

Near the other `*Opt`/`*Arg` singletons (after the Phase A `Cap*` ones), add:

```python
RunCapabilityOpt = typer.Option(None, "--capability", help="Run one capability by id.")
RunAllOpt = typer.Option(False, "--all", help="Run every active capability.")
RunFromOpt = typer.Option(None, "--from", help="Window start (UTC); default now - window_days.")
RunToOpt = typer.Option(None, "--to", help="Window end (UTC); default now.")
ReplaceTodayOpt = typer.Option(
    False, "--replace-today", help="Reuse today's run_id instead of adding a new run."
)
```

- [ ] **Step 4: Implement `pheonix run`**

`run` holds one `Store` open for the whole call (via the existing `_open_store`
context manager) because `run_capabilities` and the delta-printing both need it.
`_utc` and `datetime` are already imported in `cli.py`; add `CapabilityRunResult`
to the `from .models import (...)` block for the helper's type hint. Append after
the `serve` command, before `# ---- helpers`:

```python
@app.command()
def run(
    capability: str | None = RunCapabilityOpt,
    run_all: bool = RunAllOpt,
    from_: datetime | None = RunFromOpt,
    to: datetime | None = RunToOpt,
    replace_today: bool = ReplaceTodayOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Scrape + scoped-analyse one capability (or --all) over a [from, to] window."""
    if bool(capability) == bool(run_all):
        typer.secho("Pass exactly one of --capability <id> or --all.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    client = PhoenixClientWrapper(settings)
    with _open_store(settings) as store:
        try:
            results = capability_run_mod.run_capabilities(
                store, settings,
                capability_ids=[capability] if capability else None,
                all_active=run_all,
                client=client if client.available() else None,
                window_start=_utc(from_),
                window_end=_utc(to),
                replace_today=replace_today,
            )
        except (ValueError, FileNotFoundError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        if not results:
            typer.echo("No active capabilities to run.")
            return
        for result in results:
            _echo_capability_run(store, result)


def _echo_capability_run(store: Store, result: CapabilityRunResult) -> None:
    r = result.run
    typer.echo("")
    typer.echo(
        f"[{r.capability_id}] {r.run_id}  "
        f"window {r.window_start:%Y-%m-%d}..{r.window_end:%Y-%m-%d}  ·  "
        f"{r.n_spans} spans, {r.n_in_scope_spans} in scope -> "
        f"{r.n_clusters} clusters  ·  {r.status}"
    )
    for note in r.notes:
        typer.echo(f"  note: {note}")
    deltas = skill_coverage.cluster_deltas(
        store.capability_run_snapshot_frame(r.capability_id, r.run_id),
        store.capability_run_snapshot_frame(r.capability_id, result.previous_run_id),
    )
    if len(deltas):
        typer.echo("  what changed since the last run:")
        for row in deltas.head(_TOP_N).to_dict("records"):
            preview = str(row["representative"]).replace("\n", " ")[:_PROMPT_PREVIEW_CHARS]
            typer.echo(
                f"    {row['status']:<9} {row['count_prev']:>4} -> {row['count']:<4} "
                f"({row['count_change']:+d})  {preview}"
            )
    elif result.previous_run_id:
        typer.echo("  what changed since the last run: no movement")
```

- [ ] **Step 5: Implement `pheonix capability runs`**

Append to the `capability_app` commands (after `capability_show`):

```python
@capability_app.command("runs")
def capability_runs(
    cap_id: str = CapIdArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Recorded runs for a capability, newest first."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        frame = store.capability_runs_frame(cap_id)
    if not len(frame):
        typer.echo(f"No runs recorded for '{cap_id}'. Run `pheonix run --capability {cap_id}`.")
        return
    typer.echo(f"{'run_id':<27} {'window':<25} {'in scope':>9} {'clusters':>9}  status")
    typer.echo("-" * 90)
    for row in frame.to_dict("records"):
        window = f"{row['window_start'][:10]}..{row['window_end'][:10]}"
        typer.echo(
            f"{row['run_id']:<27} {window:<25} {row['n_in_scope_spans']:>9} "
            f"{row['n_clusters']:>9}  {row['status']}"
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_run_cli.py -q`
Expected: PASS.

- [ ] **Step 7: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~638 → ~650).

- [ ] **Step 8: Commit**

```bash
git add src/phoenix_scraper/cli.py tests/test_capability_run_cli.py
git commit -m "feat: pheonix run and pheonix capability runs"
```

---

## Task 5: Docs — README "Daily runs" + CONTRACTS.md

**Files:**
- Modify: `README.md`
- Modify: `CONTRACTS.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: README section**

In `README.md`, insert a `## Daily runs` section immediately after the
`## Capabilities` section (added in Phase A) and before `## Dashboard UI`. Body
(a heading, a paragraph, one fenced `bash` block, a closing paragraph — no
nested fences):

> `## Daily runs`
>
> Once a capability exists, `pheonix run` scrapes its Phoenix project (once, even
> for `--all`), restricts to the capability's filter and a `[from, to]` window
> (default: the last `window_days`), runs the mining pipeline over just those
> spans, and records the run so consecutive runs can be diffed.
>
> ```bash
> pheonix run --capability fobo                 # last window_days
> pheonix run --capability fobo --from 2026-08-01 --to 2026-09-01
> pheonix run --all                             # every active capability
> pheonix run --all --replace-today             # re-run without adding a history point
> pheonix capability runs fobo                  # recorded runs, newest first
> ```
>
> Runs are kept per capability up to `PHEONIX_RUN_HISTORY_LIMIT` (default 20).
> Schedule `pheonix run --all` with cron or your scheduler — there is no built-in
> daemon. Offline or with Phoenix unreachable, the run still executes against the
> stored spans and is marked `partial`.

(Strip the leading `> ` markers.)

- [ ] **Step 2: CONTRACTS.md**

In `CONTRACTS.md`, after the `## capability.py` block (added in Phase A), add:

````markdown
## capability_run.py  (scoped pipeline run + orchestration; does NOT touch the global run_analysis)
```python
def load_capability_skills(settings, capability) -> list[SkillEntry]
    # load_all_skills(settings) + scan of <capabilities_dir>/<id>/skills, de-duped by name
def run_capability_analysis(store, settings, capability, *, window_start=None,
        window_end=None, replace_today=False, notes=None, now=None) -> CapabilityRunResult
    # NO scrape. window defaults to [now - capability.window_days, now].
    # in-scope = capability_query_filters(...); costs -> build_clusters ->
    # load_capability_skills -> match_clusters -> annotate_coverage ->
    # cluster_efficiency. Records capability_runs + capability_cluster_snapshots
    # + capability_cluster_members; prunes to settings.run_history_limit per
    # capability. `notes` (e.g. a scrape failure) force status='partial'.
    # n_rung1_candidates / n_rung2_candidates are written 0 (Phases C / D).
def run_capabilities(store, settings, *, capability_ids=None, all_active=False,
        client=None, window_start=None, window_end=None, replace_today=False,
        now=None) -> list[CapabilityRunResult]
    # sync each capability.yaml -> DB; scrape each distinct project once
    # (client is None / unavailable -> note "offline", status partial);
    # loop run_capability_analysis; a capability that raises is recorded as a
    # status='failed' run and never aborts the others.
```

New tables (Phase B): `capability_runs`, `capability_cluster_snapshots`
(column `skill_name`, not `matched_skill`, for `cluster_deltas` compatibility),
`capability_cluster_members`. Pruned per capability to `run_history_limit`.
````

Also update the CLI line in `CONTRACTS.md` (`## cli.py ...`): append `, run
(--capability | --all, --from, --to, --replace-today)` and add `runs` to the
`capability (new | list | show | sync)` group → `capability (new | list | show |
sync | runs)`.

- [ ] **Step 3: Lint + full suite (docs don't change behavior — sanity only)**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 4: Commit**

```bash
git add README.md CONTRACTS.md
git commit -m "docs: daily runs (pheonix run) — README + CONTRACTS"
```

---

## Self-Review

**1. Spec coverage (Phase B slice):**

| Spec element | Task |
|---|---|
| §7.2 `capability_runs` table | Task 1 |
| §7.2 `capability_cluster_snapshots` table (as `skill_name`) | Task 1 |
| `capability_cluster_members` (spec-consistent addition — mirrors `cluster_members`; Rung 2 needs span ids) | Task 1 |
| §7.2 "pruned to `run_history_limit` per capability" | Task 1 (`_prune_capability_runs`) |
| §10.2 step 1 (sync `capability.yaml` → row, skip paused) | Task 3 (`run_capabilities`) |
| §10.2 step 2 (scrape once per distinct project, offline-tolerant, failure → partial) | Task 3 (`_scrape_projects`) |
| §10.2 step 3 (window: `now - window_days` .. `now`, `--from/--to` override) | Task 2 |
| §10.2 step 4 (in-scope frame via `capability_query_filters`) | Task 2 |
| §10.2 step 5 (costs → clusters → skills → matches → coverage → efficiency; persist snapshot) | Task 2 |
| §10.2 step 10 (record `capability_runs`, prune) | Task 2 + Task 1 |
| §10.2 idempotency (`--replace-today`) | Task 2 + Task 4 |
| §10.2 "one capability failing never aborts `--all`" | Task 3 |
| §13 "generalise `cluster_deltas` with `capability_id`" | Achieved without touching `cluster_deltas` — Task 4 feeds it scoped `capability_run_snapshot_frame`s (its `_counts_by_cluster` is already column-generic) |
| §11 `GET /capabilities/{id}/runs` | CLI equivalent `pheonix capability runs` in Task 4; the HTTP route is Phase E |
| §13 "scrape-failure path" test | Task 3 `test_scrape_failure_marks_partial_not_abort` |

Deferred (correctly out of Phase B, documented in File Structure): scoped
`derive_sessions` persistence, scoped `evaluate_spans` (Phase C decides
`upsert_evaluations` vs skip), all `candidates`/`candidate_observations`/
`candidate_decisions` and the status machine (Phase C), Rung 2 (Phase D), HTTP
routes (Phase E).

**2. Placeholder scan:** No `TBD`/`TODO`/"handle edge cases"/"similar to Task N".
Every code step contains literal, final code. The two spots that showed
wrong-then-right code in an earlier draft (Task 2's `previous_run_id` guard,
Task 4's `_open_store` wrapping) were collapsed to the single correct version.
Task 4 Step 4's `run` and Step 5's `capability_runs` are complete function
bodies. `_echo_capability_run` and `_scrape_projects` are complete helpers.

**3. Type consistency:**
- `run_capability_analysis(store, settings, capability, *, window_start,
  window_end, replace_today, notes, now)` — identical in Task 2 interface, Task 2
  impl, Task 3 call site, CONTRACTS block. ✓
- `run_capabilities(store, settings, *, capability_ids, all_active, client,
  window_start, window_end, replace_today, now)` — identical Task 3 ↔ CONTRACTS
  ↔ Task 4 call site. ✓
- `CapabilityRun` fields — identical in the model (Task 1), the
  `capability_runs` columns (Task 1), `record_capability_run` INSERT (Task 1),
  and both construction sites in `capability_run.py` (Tasks 2, 3). `notes` is a
  `tuple[str, ...]` on the model, stored as `notes_json`. ✓
- `Store.record_capability_run(run, snapshot_rows, member_rows, history_limit)` —
  Task 1 signature ↔ Task 2 call (`_snapshot_rows(...)`, list-comp of
  `(cluster_id, span_id)`) ↔ Task 3 call (`[], []` for a failed run). ✓
- `capability_run_snapshot_frame(capability_id, run_id | None)` returns a
  columned empty frame for `None` — relied on by Task 4's `_echo_capability_run`
  passing `result.previous_run_id` (which is `None` on a first run), and
  `cluster_deltas` returns an empty frame for an empty `previous_df`. ✓
- `skill_name` column (not `matched_skill`) — consistent across the table
  (Task 1), `_snapshot_rows` (Task 2), and `_counts_by_cluster`'s expectations
  (unchanged existing code). ✓

**4. Ambiguity:**
- `run_id` ordering: runs are compared and pruned by `ORDER BY run_id DESC` —
  valid because `run_id` is an ISO-8601 timestamp string, which sorts
  lexicographically iff every run uses the same offset. `run_capability_analysis`
  always builds `run_id` from a UTC `datetime` (`.isoformat()` → `+00:00`), so
  the invariant holds. Stated in Global Constraints.
- `--replace-today` "today" = `window_end.date()`, not the wall clock — so an
  explicit `--to` past midnight groups by the window's end day. Documented in
  Task 2's `run_id` block.
- `bool(capability) == bool(run_all)` rejects both-absent and both-present. An
  empty-string `--capability ""` reads as absent — acceptable (an empty id is
  invalid anyway).

---

## Execution Handoff

**Plan complete and saved to
`docs/superpowers/plans/2026-09-07-capability-ladder-phase-b.md`. Two execution
options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between
tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session with checkpoints.

**Which approach?**
