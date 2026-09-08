# Async Capability Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** An HTTP caller triggers a capability run that executes on a background
worker thread and polls a job resource for the result — without touching the
synchronous `POST /capabilities/{id}/runs`, the CLI run commands, or any existing
test.

**Architecture:** One daemon thread per API process polls a persistent
`capability_jobs` SQLite table every second and runs the oldest `queued` job via
the existing `run_capabilities(...)`, one at a time. Job state lives in the DB so
a restart can fail orphaned rows. The worker is opt-in
(`create_app(settings, *, run_jobs=False)`); only `create_app_default()` and the
Playwright smoke run it. `Store` gains WAL + `busy_timeout` so the worker and
request handlers don't collide on writes.

**Tech Stack:** Python 3.11+ (stdlib `sqlite3`, `threading`, `uuid`), FastAPI
0.141 (`lifespan`), pydantic v2, pytest, ruff, uv; React 19 + Vite 8 + TS 5.9 +
TanStack Query v5 + Vitest 5 + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-08-async-capability-runs-design.md`

## Global Constraints

- Backend suite at **770**; frontend **29** Vitest + **1** Playwright smoke.
  Nothing regresses. `uv run ruff check src tests && uv run pytest -q` — exit 0;
  `cd frontend && npm run test && npm run typecheck && npm run lint && npm run
  build` — clean; `npm run e2e` — green.
- **All existing tests build `create_app(settings)` → `run_jobs=False` → no
  thread.** Only the one lifespan test and the smoke run the real worker.
- Every Python function has type hints and returns NEW objects. TDD: failing test
  first, watch it fail, implement.
- The worker catches every exception per loop iteration — the thread never dies.
- Job `error` state is for failures that escape `run_capabilities`; a
  capability-level pipeline failure is already recorded as a `status='failed'`
  run and the job ends `done`.
- Commit `<type>: <description>`, one per task. End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/phoenix_scraper/storage.py` | modify | `capability_jobs` table + 2 indexes; `enqueue_job` / `get_job` / `capability_jobs_frame` / `claim_next_job` / `finish_job` / `reset_orphaned_jobs`; `_job_from_row`; `__enter__`/`__exit__`; `connect(timeout=5.0)` + WAL + `busy_timeout` |
| `src/phoenix_scraper/jobs.py` | create | `JobWorker` (thread lifecycle + `drain_once`), `_parse_dt` |
| `src/phoenix_scraper/api_capabilities.py` | modify | `JobRequest` model; `POST/GET /capabilities/{id}/jobs`, `GET /capabilities/{id}/jobs/{job_id}` |
| `src/phoenix_scraper/api.py` | modify | `create_app(settings, *, run_jobs=False)` + `lifespan`; `create_app_default` → `run_jobs=True`; `app.state.job_worker` |
| `src/phoenix_scraper/cli.py` | modify | `pheonix capability jobs <id>` (read-only) |
| `CONTRACTS.md` / `README.md` | modify | table, routes, worker, `run_jobs` |
| `frontend/src/api/hooks.ts` | modify | `useJob(capabilityId, jobId)` |
| `frontend/src/routes/CapabilityDetail.tsx` | modify | async "Run now" |
| `frontend/e2e/smoke.spec.ts` | modify | async run step |
| `tests/test_storage_jobs.py` | create | Store job methods + schema guard |
| `tests/test_jobs_worker.py` | create | `JobWorker.drain_once` paths |
| `tests/test_capability_jobs_api.py` | create | routes + sync-endpoint regression |
| `tests/test_jobs_lifespan.py` | create | orphan reset + real thread start/stop |
| `frontend/src/api/hooks.test.tsx` | create | `useJob` stops polling when terminal |
| `frontend/src/routes/CapabilityDetail.test.tsx` | modify | async "Run now" flow |

---

## Task 1: `capability_jobs` persistence + `Store` concurrency hardening

**Files:**
- Modify: `src/phoenix_scraper/storage.py`
- Test: `tests/test_storage_jobs.py` (create)

**Interfaces — Produces:**
```python
class Store:
    def __enter__(self) -> "Store": ...
    def __exit__(self, *exc) -> None: ...           # calls self.close()
    def enqueue_job(self, job_id: str, capability_id: str, params: dict) -> None
    def get_job(self, job_id: str) -> dict | None
    def capability_jobs_frame(self, capability_id: str, limit: int = 50) -> pd.DataFrame
    def claim_next_job(self) -> dict | None
    def finish_job(self, job_id: str, *, run_id: str | None,
                   state: str, error: str | None = None) -> None
    def reset_orphaned_jobs(self) -> int

def _job_from_row(row) -> dict
    # {job_id, capability_id, state, params: dict, run_id, error,
    #  enqueued_at, started_at, finished_at}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_storage_jobs.py`:
```python
"""Tests for the capability_jobs table CRUD on Store."""

import sqlite3

import pytest


class TestJobStore:
    def test_enqueue_then_get_round_trips(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {"replace_today": True, "from": None})
        job = tmp_store.get_job("j1")
        assert job["capability_id"] == "fobo"
        assert job["state"] == "queued"
        assert job["params"] == {"replace_today": True, "from": None}
        assert job["run_id"] is None and job["started_at"] is None

    def test_get_unknown_is_none(self, tmp_store) -> None:
        assert tmp_store.get_job("nope") is None

    def test_frame_newest_first_scoped_and_limited(self, tmp_store) -> None:
        for i in range(4):
            tmp_store.enqueue_job(f"a{i}", "fobo", {})
        tmp_store.enqueue_job("b0", "plex", {})
        frame = tmp_store.capability_jobs_frame("fobo", limit=2)
        assert list(frame["job_id"]) == ["a3", "a2"]
        assert set(tmp_store.capability_jobs_frame("plex")["job_id"]) == {"b0"}

    def test_claim_next_takes_oldest_queued_and_marks_running(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {})
        tmp_store.enqueue_job("j2", "fobo", {})
        first = tmp_store.claim_next_job()
        assert first["job_id"] == "j1"
        assert first["state"] == "running" and first["started_at"] is not None
        assert tmp_store.get_job("j1")["state"] == "running"
        assert tmp_store.claim_next_job()["job_id"] == "j2"
        assert tmp_store.claim_next_job() is None

    def test_finish_job_sets_terminal_fields(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {})
        tmp_store.claim_next_job()
        tmp_store.finish_job("j1", run_id="2026-07-21T12:00:00+00:00", state="done")
        job = tmp_store.get_job("j1")
        assert job["state"] == "done"
        assert job["run_id"] == "2026-07-21T12:00:00+00:00"
        assert job["finished_at"] is not None and job["error"] is None

    def test_finish_job_error_records_message(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {})
        tmp_store.claim_next_job()
        tmp_store.finish_job("j1", run_id=None, state="error", error="RuntimeError: boom")
        job = tmp_store.get_job("j1")
        assert job["state"] == "error" and job["error"] == "RuntimeError: boom"

    def test_reset_orphaned_jobs(self, tmp_store) -> None:
        tmp_store.enqueue_job("q", "fobo", {})          # queued
        tmp_store.enqueue_job("r", "fobo", {})
        tmp_store.claim_next_job()                       # 'q' -> running (oldest)
        tmp_store.enqueue_job("d", "fobo", {})
        tmp_store.claim_next_job()                       # 'r' -> running
        tmp_store.finish_job("r", run_id="x", state="done")
        n = tmp_store.reset_orphaned_jobs()
        assert n == 2                                    # 'q' running + 'd' queued
        assert tmp_store.get_job("q")["state"] == "error"
        assert tmp_store.get_job("d")["state"] == "error"
        assert tmp_store.get_job("r")["state"] == "done"

    def test_schema_rejects_unknown_state(self, tmp_store) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            tmp_store._conn.execute(
                "INSERT INTO capability_jobs (job_id, capability_id, state, enqueued_at) "
                "VALUES ('x', 'fobo', 'wobbly', '2026-01-01')"
            )

    def test_store_is_a_context_manager(self, tmp_path) -> None:
        from phoenix_scraper.storage import Store
        with Store(tmp_path / "cm.db") as s:
            s.enqueue_job("j1", "fobo", {})
        # connection closed on exit; a fresh Store sees the row
        with Store(tmp_path / "cm.db") as s2:
            assert s2.get_job("j1")["state"] == "queued"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_storage_jobs.py -q`
Expected: FAIL / ERROR — `Store` has no `enqueue_job` (AttributeError) and no
`__enter__`.

- [ ] **Step 3: Add the table to `_SCHEMA`**

In `src/phoenix_scraper/storage.py`, append to the `_SCHEMA` string (after the
`capability_cluster_members` block, before the closing `"""`):
```sql

CREATE TABLE IF NOT EXISTS capability_jobs (
    job_id        TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'queued'
                  CHECK (state IN ('queued', 'running', 'done', 'error')),
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
```

- [ ] **Step 4: Concurrency PRAGMAs + context manager**

In `Store.__init__`, change:
```python
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
```
to:
```python
        self._conn = sqlite3.connect(self.db_path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
```
Add right after `close`:
```python
    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
```

- [ ] **Step 5: Add the job methods**

In `src/phoenix_scraper/storage.py`, after `delete_capability` (end of the
capability CRUD block, before `# ---- capability runs`):
```python
    # ---- capability jobs (async run queue) -----------------------------------
    def enqueue_job(self, job_id: str, capability_id: str, params: dict) -> None:
        self._conn.execute(
            "INSERT INTO capability_jobs "
            "(job_id, capability_id, state, params_json, enqueued_at) "
            "VALUES (?,?,'queued',?,?)",
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
            "UPDATE capability_jobs SET state = 'running', started_at = ? "
            "WHERE job_id = ?",
            (now, row["job_id"]),
        )
        self._conn.commit()
        job = _job_from_row(row)
        job["state"] = "running"
        job["started_at"] = now
        return job

    def finish_job(
        self, job_id: str, *, run_id: str | None, state: str,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE capability_jobs SET state = ?, run_id = ?, error = ?, "
            "finished_at = ? WHERE job_id = ?",
            (state, run_id, error, _iso(datetime.now(UTC)), job_id),
        )
        self._conn.commit()

    def reset_orphaned_jobs(self) -> int:
        cur = self._conn.execute(
            "UPDATE capability_jobs SET state = 'error', "
            "error = 'interrupted by restart', finished_at = ? "
            "WHERE state IN ('queued', 'running')",
            (_iso(datetime.now(UTC)),),
        )
        self._conn.commit()
        return cur.rowcount
```

Add the row helper next to `_capability_from_row`:
```python
def _job_from_row(row: sqlite3.Row) -> dict:
    return {
        "job_id": row["job_id"],
        "capability_id": row["capability_id"],
        "state": row["state"],
        "params": json.loads(row["params_json"]),
        "run_id": row["run_id"],
        "error": row["error"],
        "enqueued_at": row["enqueued_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_storage_jobs.py -q`
Expected: PASS (9 tests).

- [ ] **Step 7: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (770 → 779). If any test asserts on raw DB files and
trips over a new `-wal` sidecar, fix that assertion to glob `*.db*` or ignore
sidecars — none is expected.

- [ ] **Step 8: Commit**

```bash
git add src/phoenix_scraper/storage.py tests/test_storage_jobs.py
git commit -m "feat: capability_jobs table + Store queue methods; WAL + busy_timeout"
```

---

## Task 2: `JobWorker`

**Files:**
- Create: `src/phoenix_scraper/jobs.py`
- Test: `tests/test_jobs_worker.py` (create)

**Interfaces:**
- Consumes: `Store.claim_next_job` / `finish_job` (Task 1);
  `capability_run.run_capabilities(store, settings, *, capability_ids=None,
  client=None, window_start=None, window_end=None, replace_today=False) ->
  list[CapabilityRunResult]`; `phoenix_client.PhoenixClientWrapper(settings)` with
  `.available() -> bool`.
- Produces:
  ```python
  class JobWorker:
      def __init__(self, settings: Settings, *, poll_seconds: float = 1.0) -> None
      def start(self) -> None          # idempotent; daemon thread
      def stop(self, timeout: float = 5.0) -> None
      def drain_once(self) -> str | None   # job_id processed, or None if queue empty

  def _parse_dt(value: str | None) -> datetime | None
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jobs_worker.py`:
```python
"""Tests for the background JobWorker (driven synchronously via drain_once)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from phoenix_scraper import capability as cap_mod
from phoenix_scraper.config import Settings
from phoenix_scraper.jobs import JobWorker
from phoenix_scraper.models import CapabilityFilter

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def job_settings(tmp_path, seeded_store):
    root = tmp_path / "caps"
    cap_mod.scaffold_capability(
        root, "fobo", name="FOBO",
        cap_filter=CapabilityFilter(workflow_stage="fobo_recon"), window_days=30,
    )
    return Settings(
        db_path=tmp_path / "test.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=root,
    ).model_copy(update={"phoenix_endpoint": None})


def test_drain_once_empty_queue_returns_none(job_settings) -> None:
    assert JobWorker(job_settings).drain_once() is None


def test_drain_once_runs_the_capability_and_marks_done(job_settings, seeded_store) -> None:
    seeded_store.enqueue_job("j1", "fobo", {"replace_today": False})
    processed = JobWorker(job_settings).drain_once()
    assert processed == "j1"
    job = seeded_store.get_job("j1")
    assert job["state"] == "done"
    assert job["run_id"] is not None
    runs = seeded_store.capability_runs_frame("fobo")
    assert job["run_id"] in set(runs["run_id"])


def test_drain_once_infra_failure_marks_error(job_settings, seeded_store, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr("phoenix_scraper.jobs.run_capabilities", boom)
    seeded_store.enqueue_job("j1", "fobo", {})
    JobWorker(job_settings).drain_once()
    job = seeded_store.get_job("j1")
    assert job["state"] == "error"
    assert "RuntimeError: db gone" in job["error"]
    assert job["run_id"] is None


def test_start_stop_is_safe_and_idempotent(job_settings) -> None:
    w = JobWorker(job_settings, poll_seconds=0.05)
    w.start()
    w.start()  # idempotent
    w.stop()
    w.stop()   # safe when already stopped
```
Note: `jobs.py` must expose `run_capabilities` at module scope (import it at the
top) so the monkeypatch target `phoenix_scraper.jobs.run_capabilities` exists.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_jobs_worker.py -q`
Expected: FAIL — `ModuleNotFoundError: phoenix_scraper.jobs`.

- [ ] **Step 3: Implement `jobs.py`**

Create `src/phoenix_scraper/jobs.py`:
```python
"""Background worker for capability runs — one daemon thread, one run at a time.

Polls the capability_jobs table every `poll_seconds`; runs the oldest queued job
via run_capabilities and records the outcome back on the row. Opt-in: only
api.create_app(..., run_jobs=True) starts it.
"""

import logging
import threading
from datetime import datetime

from .capability_run import run_capabilities
from .config import Settings
from .phoenix_client import PhoenixClientWrapper
from .storage import Store

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class JobWorker:
    def __init__(self, settings: Settings, *, poll_seconds: float = 1.0) -> None:
        self.settings = settings
        self.poll_seconds = poll_seconds
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="pheonix-jobs", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.drain_once()
            except Exception:  # noqa: BLE001 — the worker thread must never die
                logger.exception("job worker iteration failed")

    def drain_once(self) -> str | None:
        with Store(self.settings.db_path) as store:
            job = store.claim_next_job()
            if job is None:
                return None
            self._run(store, job)
            return job["job_id"]

    def _run(self, store: Store, job: dict) -> None:
        params = job["params"]
        try:
            client = PhoenixClientWrapper(self.settings)
            results = run_capabilities(
                store, self.settings, capability_ids=[job["capability_id"]],
                client=client if client.available() else None,
                window_start=_parse_dt(params.get("from")),
                window_end=_parse_dt(params.get("to")),
                replace_today=bool(params.get("replace_today", False)),
            )
            run_id = results[0].run.run_id if results else None
            store.finish_job(job["job_id"], run_id=run_id, state="done")
        except Exception as exc:  # noqa: BLE001 — infra failure -> job error
            logger.exception("capability job %s failed", job["job_id"])
            store.finish_job(
                job["job_id"], run_id=None, state="error",
                error=f"{type(exc).__name__}: {exc}"[:2000],
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_jobs_worker.py -q`
Expected: PASS (4 tests). `test_start_stop_is_safe_and_idempotent` spins a real
thread for ~50ms and joins it.

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (779 → 783).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/jobs.py tests/test_jobs_worker.py
git commit -m "feat: JobWorker — background capability runs, one at a time"
```

---

## Task 3: Job API routes

**Files:**
- Modify: `src/phoenix_scraper/api_capabilities.py`
- Test: `tests/test_capability_jobs_api.py` (create)

**Interfaces:**
- Consumes: `Store` job methods (Task 1); `JobWorker(settings).drain_once()`
  (Task 2, used by the test only); `_frame_response` (lazy import from `.api`).
- Produces routes on the capability router:
  - `POST /capabilities/{cap_id}/jobs` → 202 `{job_id, capability_id, state}`
  - `GET /capabilities/{cap_id}/jobs` → frame response `capability_jobs`
  - `GET /capabilities/{cap_id}/jobs/{job_id}` → the `_job_from_row` dict (404 if
    absent or the `capability_id` doesn't match)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_capability_jobs_api.py`:
```python
"""API tests for the async capability-run job routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings
from phoenix_scraper.jobs import JobWorker

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def ctx(tmp_path: Path):
    settings = Settings(
        db_path=tmp_path / "api.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})
    with TestClient(create_app(settings)) as c:
        c.post("/demo/seed")
        c.post("/capabilities", json={"id": "plex", "name": "PLEX",
                                      "filter": {"workflow_stage": "plex"}})
        yield c, settings


def test_enqueue_returns_202_and_persists(ctx) -> None:
    c, settings = ctx
    r = c.post("/capabilities/plex/jobs", json={})
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "queued" and body["capability_id"] == "plex"
    listed = c.get("/capabilities/plex/jobs").json()
    assert [j["job_id"] for j in listed] == [body["job_id"]]


def test_enqueue_unknown_capability_404(ctx) -> None:
    c, _ = ctx
    assert c.post("/capabilities/ghost/jobs", json={}).status_code == 404


def test_job_lifecycle_queued_then_done(ctx) -> None:
    c, settings = ctx
    job_id = c.post("/capabilities/plex/jobs", json={}).json()["job_id"]
    assert c.get(f"/capabilities/plex/jobs/{job_id}").json()["state"] == "queued"

    assert JobWorker(settings).drain_once() == job_id

    done = c.get(f"/capabilities/plex/jobs/{job_id}").json()
    assert done["state"] == "done" and done["run_id"]
    run = c.get(f"/capabilities/plex/runs/{done['run_id']}")
    assert run.status_code == 200


def test_job_id_under_wrong_capability_404(ctx) -> None:
    c, _ = ctx
    job_id = c.post("/capabilities/plex/jobs", json={}).json()["job_id"]
    c.post("/capabilities", json={"id": "fobo", "name": "F",
                                  "filter": {"workflow_stage": "fobo_recon"}})
    assert c.get(f"/capabilities/fobo/jobs/{job_id}").status_code == 404


def test_sync_run_endpoint_still_synchronous(ctx) -> None:
    c, _ = ctx
    r = c.post("/capabilities/plex/runs", json={})
    assert r.status_code == 200
    assert "run_id" in r.json() and "status" in r.json()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_capability_jobs_api.py -q`
Expected: FAIL — `POST /capabilities/plex/jobs` 404s (route not defined), so the
202 assertion fails.

- [ ] **Step 3: Implement the routes**

In `src/phoenix_scraper/api_capabilities.py`:

Add to the imports at the top:
```python
import uuid
```
Add the request model next to `RunRequest`:
```python
class JobRequest(BaseModel):
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    replace_today: bool = False

    model_config = {"populate_by_name": True}
```
In `_register_run_routes`, after the existing `/runs/{run_id}` route:
```python
    @router.post("/capabilities/{cap_id}/jobs", status_code=202)
    def enqueue_run_job(cap_id: str, body: JobRequest) -> dict:
        try:
            capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        job_id = uuid.uuid4().hex
        params = {
            "from": body.from_.isoformat() if body.from_ else None,
            "to": body.to.isoformat() if body.to else None,
            "replace_today": body.replace_today,
        }
        with _store() as store:
            store.enqueue_job(job_id, cap_id, params)
        return {"job_id": job_id, "capability_id": cap_id, "state": "queued"}

    @router.get("/capabilities/{cap_id}/jobs")
    def list_run_jobs(cap_id: str, fmt: str = "json"):
        from .api import _frame_response
        with _store() as store:
            df = store.capability_jobs_frame(cap_id)
        return _frame_response(df, fmt, "capability_jobs")

    @router.get("/capabilities/{cap_id}/jobs/{job_id}")
    def one_run_job(cap_id: str, job_id: str) -> dict:
        with _store() as store:
            job = store.get_job(job_id)
        if job is None or job["capability_id"] != cap_id:
            raise HTTPException(status_code=404, detail="No such job")
        return job
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_jobs_api.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (783 → 788). `tests/test_ladder_api.py` and
`test_scoped_analytics_api.py` unchanged (no worker; new routes are additive).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/api_capabilities.py tests/test_capability_jobs_api.py
git commit -m "feat: POST/GET /capabilities/{id}/jobs — enqueue + poll async runs"
```

---

## Task 4: App lifespan wiring (`run_jobs` opt-in)

**Files:**
- Modify: `src/phoenix_scraper/api.py`
- Test: `tests/test_jobs_lifespan.py` (create)

**Interfaces:**
- Consumes: `JobWorker` (Task 2); `Store.reset_orphaned_jobs` (Task 1).
- Produces: `create_app(settings: Settings, *, run_jobs: bool = False) -> FastAPI`
  — when `run_jobs`, a `lifespan` resets orphaned jobs then starts a `JobWorker`,
  and stops it on shutdown; `app.state.job_worker` is the worker or `None`.
  `create_app_default()` passes `run_jobs=True`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs_lifespan.py`:
```python
"""The job worker lifespan: orphan reset on startup, clean thread stop."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings
from phoenix_scraper.storage import Store

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "api.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})


def test_startup_fails_orphaned_jobs_and_worker_stops(settings) -> None:
    with Store(settings.db_path) as s:
        s.enqueue_job("stuck", "fobo", {})
        s.claim_next_job()  # 'stuck' -> running, as if a crash left it

    app = create_app(settings, run_jobs=True)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert app.state.job_worker is not None
    # lifespan shutdown ran: worker thread joined
    assert app.state.job_worker._thread is None

    with Store(settings.db_path) as s:
        job = s.get_job("stuck")
    assert job["state"] == "error"
    assert job["error"] == "interrupted by restart"


def test_default_create_app_has_no_worker(settings) -> None:
    app = create_app(settings)
    assert app.state.job_worker is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_jobs_lifespan.py -q`
Expected: FAIL — `create_app()` has no `run_jobs` kw (TypeError) / no
`app.state.job_worker`.

- [ ] **Step 3: Implement the lifespan**

In `src/phoenix_scraper/api.py`:

Add imports near the top (with the other stdlib imports):
```python
import logging
from contextlib import asynccontextmanager
```
```python
logger = logging.getLogger(__name__)
```
(if a module logger is not already defined — check; add only if missing).

Change the signature and `FastAPI(...)` construction:
```python
def create_app(settings: Settings, *, run_jobs: bool = False) -> FastAPI:
    """Build the API around one Settings instance (dependency-injectable for tests).

    run_jobs=True starts the background capability-run worker (create_app_default
    / real serving). Tests pass run_jobs=False (the default) — no thread.
    """
    from .jobs import JobWorker

    worker = JobWorker(settings) if run_jobs else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if worker is not None:
            with Store(settings.db_path) as store:
                n = store.reset_orphaned_jobs()
            if n:
                logger.warning("marked %d orphaned capability job(s) as error", n)
            worker.start()
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()

    app = FastAPI(
        title="Pheonix prompt miner", version=__version__, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.job_worker = worker
```
(The `from .jobs import JobWorker` is a function-local import to avoid a circular
import: `jobs.py` imports `capability_run`, which does not import `api`, so a
top-level import is likely fine too — use the local import to be safe and match
the `_frame_response` lazy-import pattern already in this codebase.)

Change `create_app_default`:
```python
def create_app_default() -> FastAPI:
    """Zero-arg factory for `uvicorn phoenix_scraper.api:create_app_default --factory`."""
    return create_app(load_settings(), run_jobs=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_jobs_lifespan.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (788 → 790). Every other API test still constructs
`create_app(settings)` → `worker is None` → lifespan is a no-op.

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/api.py tests/test_jobs_lifespan.py
git commit -m "feat: opt-in job worker lifespan; create_app_default runs it"
```

---

## Task 5: CLI `pheonix capability jobs <id>`

**Files:**
- Modify: `src/phoenix_scraper/cli.py`
- Test: `tests/test_capability_cli.py` (append)

**Interfaces:**
- Consumes: `Store.capability_jobs_frame` (Task 1). Mirrors the existing
  `capability_runs` command (cli.py ~line 858).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability_cli.py` (match its existing runner/fixtures —
it uses `typer.testing.CliRunner` and a `settings`/`tmp_path` pattern; inspect
the file and follow it). The test:
```python
def test_capability_jobs_lists_rows(tmp_path, monkeypatch) -> None:
    # scaffold a capability + enqueue one job directly on the store, then
    # assert `pheonix capability jobs <id>` prints the job_id and its state.
    from phoenix_scraper import capability as cap_mod
    from phoenix_scraper.models import CapabilityFilter
    from phoenix_scraper.storage import Store

    root = tmp_path / "caps"
    cap_mod.scaffold_capability(root, "fobo", cap_filter=CapabilityFilter())
    db = tmp_path / "c.db"
    with Store(db) as s:
        s.enqueue_job("job-abc", "fobo", {})

    result = runner.invoke(app, [
        "capability", "jobs", "fobo", "--db", str(db),
        "--capabilities-dir", str(root),
    ])
    assert result.exit_code == 0
    assert "job-abc" in result.stdout
    assert "queued" in result.stdout


def test_capability_jobs_empty(tmp_path) -> None:
    from phoenix_scraper import capability as cap_mod
    from phoenix_scraper.models import CapabilityFilter
    root = tmp_path / "caps"
    cap_mod.scaffold_capability(root, "fobo", cap_filter=CapabilityFilter())
    result = runner.invoke(app, [
        "capability", "jobs", "fobo",
        "--db", str(tmp_path / "c.db"), "--capabilities-dir", str(root),
    ])
    assert result.exit_code == 0
    assert "No jobs" in result.stdout
```
(Use whatever `runner` / `app` names the file already imports.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_capability_cli.py -q -k jobs`
Expected: FAIL — no `jobs` subcommand (`exit_code != 0`, "No such command").

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/cli.py`, after `capability_runs` (ends ~line 878):
```python
@capability_app.command("jobs")
def capability_jobs(
    cap_id: str = CapIdArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Background run jobs for a capability, newest first."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        frame = store.capability_jobs_frame(cap_id)
    if not len(frame):
        typer.echo(f"No jobs for '{cap_id}'.")
        return
    typer.echo(f"{'job_id':<34} {'state':<9} {'run_id':<27} enqueued")
    typer.echo("-" * 90)
    for row in frame.to_dict("records"):
        run_id = str(row["run_id"] or "-")
        typer.echo(
            f"{row['job_id']:<34} {row['state']:<9} {run_id:<27} "
            f"{row['enqueued_at'][:19]}"
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_capability_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (790 → 792).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/cli.py tests/test_capability_cli.py
git commit -m "feat: pheonix capability jobs <id> — list background run jobs"
```

---

## Task 6: SPA — `useJob` hook + async "Run now"

**Files:**
- Modify: `frontend/src/api/hooks.ts`, `frontend/src/routes/CapabilityDetail.tsx`,
  `frontend/e2e/smoke.spec.ts`
- Create: `frontend/src/api/hooks.test.tsx`
- Modify: `frontend/src/routes/CapabilityDetail.test.tsx`

**Interfaces:**
- Consumes: `POST /capabilities/{id}/jobs` → `{job_id, state}`;
  `GET /capabilities/{id}/jobs/{job_id}` → `{state, run_id, error, ...}` (Task 3).
- Produces: `useJob(capabilityId: string, jobId: string | null)` — a TanStack
  Query that polls every 1500ms until `state` is `done` or `error`.

- [ ] **Step 1: Read the current files**

Read `frontend/src/api/hooks.ts` (find the `fetchJson` import, the existing
`useScoped` / mutation patterns), `frontend/src/routes/CapabilityDetail.tsx` (the
current "Run now" button — a `useMutation` on `POST .../runs` + `toast` +
`queryClient.invalidateQueries`), `frontend/src/routes/CapabilityDetail.test.tsx`
(the current "Run now" test + its fetch mock), and `frontend/e2e/smoke.spec.ts`
(the "run it" step). The steps below assume that shape; adapt names to what you
find.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/api/hooks.test.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useJob } from "./hooks";

afterEach(() => vi.restoreAllMocks());

test("useJob polls until the job is terminal, then stops", async () => {
  let calls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
    calls += 1;
    return new Response(
      JSON.stringify({ state: calls >= 2 ? "done" : "running", run_id: "r1" }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { result } = renderHook(() => useJob("plex", "job-1"), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });

  await waitFor(() => expect(result.current.data?.state).toBe("done"));
  const settled = calls;
  await new Promise((r) => setTimeout(r, 1800));
  expect(calls).toBe(settled); // no further polls after 'done'
});

test("useJob is disabled when jobId is null", () => {
  const spy = vi.spyOn(globalThis, "fetch");
  const qc = new QueryClient();
  renderHook(() => useJob("plex", null), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  });
  expect(spy).not.toHaveBeenCalled();
});
```

Extend `frontend/src/routes/CapabilityDetail.test.tsx` — replace/augment the
"Run now" test so the mock answers `POST /capabilities/:id/jobs` with
`{ job_id: "j1", state: "queued" }` and `GET /capabilities/:id/jobs/j1` with
`{ state: "done", run_id: "r1" }`, then assert the success toast text appears
(`await screen.findByText(/run complete/i)` or the existing toast assertion) and
that the board query refetches (a second `GET /capabilities/:id` or
`/candidates`). Keep it consistent with the file's existing mock helper.

- [ ] **Step 3: Run to verify they fail**

Run: `cd frontend && npm run test -- --run hooks CapabilityDetail`
Expected: FAIL — `useJob` is not exported; the Run-now test's new endpoints
aren't handled.

- [ ] **Step 4: Add `useJob`**

In `frontend/src/api/hooks.ts` (match the existing import of `fetchJson` and the
`useQuery` usage in `useScoped`):
```ts
export function useJob(capabilityId: string, jobId: string | null) {
  return useQuery({
    queryKey: ["job", capabilityId, jobId],
    queryFn: () =>
      fetchJson(`/capabilities/${capabilityId}/jobs/${jobId}`) as Promise<{
        state: "queued" | "running" | "done" | "error";
        run_id: string | null;
        error: string | null;
      }>,
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.state;
      return s === "done" || s === "error" ? false : 1500;
    },
  });
}
```

- [ ] **Step 5: Async "Run now" in `CapabilityDetail.tsx`**

Replace the current run mutation with the enqueue + poll flow:
```tsx
const [jobId, setJobId] = useState<string | null>(null);
const qc = useQueryClient();

const enqueue = useMutation({
  mutationFn: () =>
    fetchJson(`/capabilities/${id}/jobs`, { method: "POST", body: JSON.stringify({}) }) as
      Promise<{ job_id: string }>,
  onSuccess: (d) => setJobId(d.job_id),
  onError: (e) => toast.error((e as Error).message),
});

const job = useJob(id!, jobId);

useEffect(() => {
  if (!job.data) return;
  if (job.data.state === "done") {
    toast.success("run complete");
    qc.invalidateQueries({ queryKey: ["capability", id] });
    qc.invalidateQueries({ queryKey: ["board", id] });
    setJobId(null);
  } else if (job.data.state === "error") {
    toast.error(job.data.error ?? "run failed");
    setJobId(null);
  }
}, [job.data, id, qc]);

const running = enqueue.isPending || jobId !== null;
// <Button onClick={() => enqueue.mutate()} disabled={running}>
//   {running ? "running…" : "Run now"}
// </Button>
```
Match the real query keys the file uses for the capability + board queries (read
them in Step 1) — the invalidate calls must use those exact keys. Keep the
existing button component and styling.

- [ ] **Step 6: Run to verify they pass**

Run: `cd frontend && npm run test -- --run hooks CapabilityDetail`
Expected: PASS.

- [ ] **Step 7: Full frontend gate**

Run: `cd frontend && npm run test && npm run typecheck && npm run lint && npm run build`
Expected: all clean; Vitest 29 → ~32.

- [ ] **Step 8: Update the Playwright smoke**

In `frontend/e2e/smoke.spec.ts`, the run step: after clicking "Run now", wait for
the button to leave the "running…" state and for the board / run summary to
appear, e.g.:
```ts
await page.getByRole("button", { name: /run now/i }).click();
await expect(page.getByRole("button", { name: /run now/i })).toBeEnabled({ timeout: 20_000 });
// then the existing board assertions
```
The smoke's API runs with `create_app_default` (`run_jobs=True`), Phoenix is
offline so the run is fast, but it now goes through the queue + a poll cycle.

- [ ] **Step 9: Run the smoke**

Run: `cd frontend && rm -rf .e2e && npm run e2e`
Expected: PASS (1 test).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/hooks.ts frontend/src/api/hooks.test.tsx \
  frontend/src/routes/CapabilityDetail.tsx frontend/src/routes/CapabilityDetail.test.tsx \
  frontend/e2e/smoke.spec.ts
git commit -m "feat: SPA Run now enqueues a background job and polls to completion"
```

---

## Task 7: Docs — `CONTRACTS.md` + `README.md`

**Files:** `CONTRACTS.md`, `README.md`

- [ ] **Step 1: `CONTRACTS.md` — storage**

Under the `storage.py` section, near the capability methods, add:
```
# capability_jobs (async run queue):
def enqueue_job(job_id, capability_id, params: dict) -> None
def get_job(job_id) -> dict | None          # params comes back as a dict
def capability_jobs_frame(capability_id, limit=50) -> DataFrame   # newest first
def claim_next_job() -> dict | None          # oldest 'queued' -> 'running'
def finish_job(job_id, *, run_id, state, error=None) -> None      # state done|error
def reset_orphaned_jobs() -> int             # startup: queued/running -> error
# Store is a context manager; __init__ opens with WAL + busy_timeout=5000.
```

- [ ] **Step 2: `CONTRACTS.md` — jobs.py + api**

Add a section:
```
## jobs.py  (background capability-run worker — one daemon thread, one run at a time)
```python
class JobWorker(settings, *, poll_seconds=1.0)
    # start() / stop(timeout=5) / drain_once() -> job_id | None
    # _loop polls claim_next_job every poll_seconds; each iteration wrapped so the
    # thread never dies. A capability that fails inside run_capabilities ends the
    # job 'done' (the run row carries status='failed'); only escapes -> 'error'.
```
```
And under the capabilities API routes:
```
POST /capabilities/{id}/jobs {from?,to?,replace_today?} -> 202 {job_id, state}
GET  /capabilities/{id}/jobs                            -> rows, newest first
GET  /capabilities/{id}/jobs/{job_id}                   -> {state, run_id, error, ...}
# create_app(settings, *, run_jobs=False); create_app_default() -> run_jobs=True.
```

- [ ] **Step 3: `README.md` — background runs**

In the "## Daily runs" section, after the sync `pheonix run` description, add:
```markdown
### Background runs (API)

The HTTP API can run a capability without blocking the request. `POST
/capabilities/<id>/jobs` returns `202` with a `job_id`; poll `GET
/capabilities/<id>/jobs/<job_id>` until `state` is `done` (with a `run_id`) or
`error`. A single worker thread inside the API process drains the queue one run
at a time — it starts with `pheonix serve` / the uvicorn factory, and a restart
marks any interrupted job `error`. The `pheonix run` CLI stays synchronous;
`pheonix capability jobs <id>` lists the job history.
```

- [ ] **Step 4: Verify + full suite**

Run: `uv run pytest -q` (docs don't affect it — sanity) and read both diffs.
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add CONTRACTS.md README.md
git commit -m "docs: async capability runs — jobs table, worker, /jobs routes"
```

---

## Self-Review

- **Spec coverage:** table + Store methods → Task 1; `JobWorker` → Task 2; routes
  → Task 3; lifespan + `run_jobs` → Task 4; CLI → Task 5; SPA + smoke → Task 6;
  docs → Task 7. Non-goals (parallel workers, cancellation, retries, scheduler)
  appear nowhere in the tasks.
- **No existing test changes:** Tasks 1–5 add tests and additive code. The only
  edits to existing test files are appends (`test_capability_cli.py`) and the SPA
  Run-now test (Task 6), whose behaviour genuinely changes. `create_app(settings)`
  default `run_jobs=False` keeps all ~200 API tests thread-free.
- **Type consistency:** `claim_next_job`/`get_job` return the same `_job_from_row`
  dict shape the routes return and the tests assert. `JobWorker.drain_once() ->
  str | None` matches its tests. `run_capabilities(...)` kwargs match CONTRACTS.
  `_parse_dt` feeds `window_start`/`window_end: datetime | None`.
- **Placeholder scan:** every step has literal code except Task 6 Steps 1/5 which
  explicitly say "read the file first, match its query keys" — unavoidable
  because the exact TanStack keys live in a file not yet quoted; the shape is
  fully specified.
- **Circular import:** `jobs.py` imports `capability_run` + `phoenix_client` +
  `storage` + `config` — none import `api`. `api.py` imports `JobWorker` inside
  `create_app`. Safe.
- **WAL risk:** widest blast radius (every `Store` open). No `:memory:` DBs, no
  test asserts on raw journal files (grep-checked). Task 1 Step 7 runs the whole
  suite to confirm.
- **Ambiguity:** a restart fails `queued` jobs too (Task 1
  `reset_orphaned_jobs` WHERE `state IN ('queued','running')`) — the client
  re-triggers; no partial-resume.
- **Test count:** backend 770 → ~792; frontend 29 → ~32 + smoke stays 1.
