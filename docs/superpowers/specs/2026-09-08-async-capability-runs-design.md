# Async Capability Runs — Design

**Status:** approved 2026-09-08. Supersedes the "job queue for long synchronous
runs (§16.4)" line in the capability-ladder spec's deferred list.

**Problem.** `POST /capabilities/{id}/runs` and `pheonix run --all` execute the
scrape + mining pipeline synchronously. A run over a large Phoenix project (or
several, for `--all`) blocks the HTTP request for its whole duration — the SPA's
"Run now" button spins with no feedback and a slow proxy can time it out.

**Goal.** An HTTP caller can trigger a capability run that executes in the
background and poll for its result, without changing the existing synchronous
endpoint, the CLI, or any current test.

**Non-goals.** Parallel workers; job cancellation; automatic retries;
cron/interval scheduling; a generic background-job framework beyond capability
runs; distributing work across processes or machines.

---

## Architecture

One daemon thread per API process drains a persistent `capability_jobs` table,
**one run at a time**, polling every second. Job state lives in SQLite so it
survives a restart (orphaned rows are failed on the next startup). The trigger is
a new job resource (`POST /capabilities/{id}/jobs`); the synchronous
`POST /capabilities/{id}/runs` is unchanged.

```
client → POST /capabilities/{id}/jobs {from?,to?,replace_today?}
         → 202 {job_id, state:"queued"}          (row inserted, state=queued)

worker thread (poll 1s):
  claim_next_job()  → oldest queued row → state=running, started_at=now
  run_capabilities(store, settings, capability_ids=[cap_id], client=…)
  finish_job(job_id, run_id=<recorded run>, state="done")     (or "error"+msg)

client → GET /capabilities/{id}/jobs/{job_id} (poll)
         → {state, run_id, error, enqueued_at, started_at, finished_at}
         state=="done" → GET the run summary / refetch the board
```

### Why this shape

- **In-process thread, not `BackgroundTasks`**: we need a real queue (one run at
  a time), restart recovery, and observable state — `BackgroundTasks` gives none
  of these.
- **Polling the table, not an in-memory queue**: the worker stays stateless.
  "Enqueue" is a plain INSERT; a queued row left by a restart is picked up
  naturally; there is no queue to re-populate. Idle cost is one indexed
  `SELECT … LIMIT 1` per second.
- **`Store` per drain iteration, not a long-lived worker connection**: keeps the
  sqlite connection on the thread that uses it and means shutdown never has to
  interrupt an open connection. `_SCHEMA` is `CREATE TABLE IF NOT EXISTS` only —
  re-running it per iteration is microseconds.
- **New job resource, not `?async=true`**: one route, one response shape. The
  synchronous endpoint and its callers (5 backend tests, the Playwright smoke)
  are untouched.
- **Opt-in worker (`create_app(settings, *, run_jobs=False)`)**: every existing
  test builds `create_app(settings)` and gets no thread — zero behavioural
  change. Only `create_app_default()` (uvicorn + the smoke) runs the worker.

---

## Components

### 1. `capability_jobs` table  (`storage.py` `_SCHEMA`)

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

`job_id` is `uuid.uuid4().hex`. `params_json` holds `{"from": <iso|null>, "to":
<iso|null>, "replace_today": <bool>}`. Timestamps are ISO-8601 UTC strings
(`_iso(datetime.now(UTC))`, matching every other table).

### 2. `Store` methods  (`storage.py`)

```python
def enqueue_job(self, job_id: str, capability_id: str, params: dict) -> None
    # INSERT one row, state='queued', enqueued_at=now.

def get_job(self, job_id: str) -> dict | None
    # one row as a plain dict (json fields left as strings), or None.

def capability_jobs_frame(self, capability_id: str, limit: int = 50) -> pd.DataFrame
    # rows for this capability, ORDER BY enqueued_at DESC, LIMIT limit.

def claim_next_job(self) -> dict | None
    # the oldest state='queued' row across ALL capabilities:
    #   SELECT … WHERE state='queued' ORDER BY enqueued_at LIMIT 1
    #   → if found: UPDATE … SET state='running', started_at=now WHERE job_id=?
    #   → return the row (as a dict, with state/started_at reflecting the update)
    # Only one worker calls this, so SELECT-then-UPDATE needs no extra locking.

def finish_job(self, job_id: str, *, run_id: str | None,
               state: str, error: str | None = None) -> None
    # UPDATE … SET state=?, run_id=?, error=?, finished_at=now WHERE job_id=?
    # state is 'done' or 'error'.

def reset_orphaned_jobs(self) -> int
    # UPDATE … SET state='error', error='interrupted by restart', finished_at=now
    #   WHERE state IN ('queued', 'running')
    # returns cur.rowcount. Called once at app startup.
```

`_job_from_row(row) -> dict` helper mirrors `_capability_from_row`: returns
`{job_id, capability_id, state, params: json.loads(params_json), run_id, error,
enqueued_at, started_at, finished_at}`.

### 3. `Store.__init__` concurrency hardening  (`storage.py`)

```python
self._conn = sqlite3.connect(self.db_path, timeout=5.0)
self._conn.row_factory = sqlite3.Row
self._conn.execute("PRAGMA journal_mode = WAL")
self._conn.execute("PRAGMA busy_timeout = 5000")
self._conn.executescript(_SCHEMA)
self._conn.commit()
```

WAL lets a reader and the single writer proceed without blocking; `busy_timeout`
makes a write that still hits a lock wait up to 5 s instead of raising
`database is locked`. Local filesystem only (already a POC constraint). The
`-wal` / `-shm` sidecar files sit next to `pheonix.db` under the gitignored
`data/` dir.

### 4. `JobWorker`  (new `src/phoenix_scraper/jobs.py`)

```python
class JobWorker:
    def __init__(self, settings: Settings, *, poll_seconds: float = 1.0) -> None: ...

    def start(self) -> None
        # idempotent; spawns a daemon Thread(target=self._loop, name="pheonix-jobs")

    def stop(self, timeout: float = 5.0) -> None
        # set the stop Event, join(timeout). Safe to call if never started.

    def drain_once(self) -> str | None
        # one claim → run → finish cycle against a fresh Store.
        # returns the job_id it processed, or None if the queue was empty.
        # This is the unit of work; tests call it directly, no thread.

    def _loop(self) -> None
        # while not self._stop.wait(self.poll_seconds):
        #     try: self.drain_once()
        #     except Exception: logger.exception("job worker iteration failed")
```

`drain_once` body:
```python
store = Store(self.settings.db_path)
try:
    job = store.claim_next_job()
    if job is None:
        return None
    self._run(store, job)
    return job["job_id"]
finally:
    store.close()
```

`_run(store, job)`:
```python
from .capability_run import run_capabilities
from .phoenix_client import PhoenixClientWrapper

params = job["params"]  # already a dict via _job_from_row
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
except Exception as exc:                       # noqa: BLE001 — infra failure
    logger.exception("capability job %s failed", job["job_id"])
    store.finish_job(
        job["job_id"], run_id=None, state="error",
        error=f"{type(exc).__name__}: {exc}"[:2000],
    )
```

Note the split: a capability whose pipeline raises is already caught *inside*
`run_capabilities`, which records a `capability_runs` row with `status='failed'`
and returns normally — so that job ends **`done`** with a `run_id` pointing at
the failed run. Job **`error`** is only for failures that escape
`run_capabilities` (DB unavailable, a bug). Both are terminal and visible via
`GET …/jobs/{id}`.

`_parse_dt(s: str | None) -> datetime | None` = `datetime.fromisoformat(s)` when
truthy else `None`.

### 5. API routes  (`api_capabilities.py`, inside `_register_run_routes`)

```python
class JobRequest(BaseModel):
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    replace_today: bool = False
    model_config = {"populate_by_name": True}
```

```python
@router.post("/capabilities/{cap_id}/jobs", status_code=202)
def enqueue_job(cap_id: str, body: JobRequest) -> dict:
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
def list_jobs(cap_id: str, fmt: str = "json"):
    from .api import _frame_response
    with _store() as store:
        df = store.capability_jobs_frame(cap_id)
    return _frame_response(df, fmt, "capability_jobs")

@router.get("/capabilities/{cap_id}/jobs/{job_id}")
def one_job(cap_id: str, job_id: str) -> dict:
    with _store() as store:
        job = store.get_job(job_id)
    if job is None or job["capability_id"] != cap_id:
        raise HTTPException(status_code=404, detail="No such job")
    return job
```

Route order inside the router: `/jobs` and `/jobs/{job_id}` are unambiguous
against the existing `/runs`, `/runs/delta`, `/runs/{run_id}` — no ordering
constraint, but register them next to the run routes for readability.

`_frame_response` already handles the empty-frame case (returns `[]` / an empty
CSV), so `GET …/jobs` on a capability with no jobs is a clean empty list.

### 6. App wiring  (`api.py`)

`create_app` gains a keyword-only `run_jobs: bool = False`:

```python
def create_app(settings: Settings, *, run_jobs: bool = False) -> FastAPI:
    worker = JobWorker(settings) if run_jobs else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if worker is not None:
            with Store(settings.db_path) as s:
                n = s.reset_orphaned_jobs()
            if n:
                logger.warning("marked %d orphaned capability job(s) as error", n)
            worker.start()
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()

    app = FastAPI(title="Pheonix prompt miner", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.job_worker = worker
    ...
```

```python
def create_app_default() -> FastAPI:
    return create_app(load_settings(), run_jobs=True)
```

Existing tests call `create_app(settings)` → `run_jobs=False` → `worker is None`
→ the lifespan is a no-op → **no thread, no behaviour change**. `with
TestClient(create_app(settings))` still works exactly as today.

### 7. CLI  (`cli.py`)

`pheonix run` / `pheonix run --all` unchanged — synchronous, as a terminal
command should be. Add a read-only listing that mirrors `capability runs`:

```python
@capability_app.command("jobs")
def capability_jobs(cap_id: str = CapIdArg, db=DbOpt, capabilities_dir=CapabilitiesDirOpt):
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
        typer.echo(
            f"{row['job_id']:<34} {row['state']:<9} "
            f"{str(row['run_id'] or '-'):<27} {row['enqueued_at'][:19]}"
        )
```

### 8. SPA  (`frontend/`)

**`src/api/hooks.ts`** — a job hook that polls while the job is non-terminal:

```ts
export function useJob(capabilityId: string, jobId: string | null) {
  return useQuery({
    queryKey: ["job", capabilityId, jobId],
    queryFn: () => fetchJson(`/capabilities/${capabilityId}/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = (q.state.data as { state?: string } | undefined)?.state;
      return s === "done" || s === "error" ? false : 1500;
    },
  });
}
```

**`src/routes/CapabilityDetail.tsx`** — "Run now" switches from the sync POST to:
1. `POST /capabilities/{id}/jobs` → store `job_id` in component state, button →
   `disabled`, label "running…".
2. `useJob(id, jobId)` polls. On `state==="done"` → `toast.success("run
   complete")`, invalidate the capability + board queries, clear `jobId`. On
   `state==="error"` → `toast.error(job.error ?? "run failed")`, clear `jobId`.

**`e2e/smoke.spec.ts`** — the "run it" step becomes: click Run now, then
`await expect(...).toContainText(...)` / wait for the board, allowing for the
poll cycle (the smoke's Phoenix is offline so the run is fast but goes through
the queue). Bump the step's timeout if needed (config already at 45 s).

### 9. Docs

- `CONTRACTS.md`: a `## jobs.py` block (`JobWorker` surface); the three new routes
  under the capabilities API section; the `capability_jobs` table + Store methods
  under `storage.py`; note `create_app(settings, *, run_jobs=False)`.
- `README.md`: "Daily runs" gains a short "Background runs (API)" paragraph —
  `POST /capabilities/{id}/jobs` + poll `GET …/jobs/{job_id}`; the worker runs
  inside `pheonix serve` / the uvicorn factory; the CLI stays synchronous.

---

## Error handling & edge cases

| Situation | Behaviour |
|---|---|
| Enqueue for an unknown capability | 404, no row inserted |
| Capability pipeline raises | caught in `run_capabilities` → `capability_runs` row `status='failed'`; job → `done` with that `run_id` |
| DB error / unexpected exception in the worker | job → `error`, `error` = `"ExcType: msg"` (≤2000 chars), `run_id` null |
| Server restart mid-run | next startup: `reset_orphaned_jobs()` → that row `error "interrupted by restart"`; the client's poll sees `error` |
| Server restart with queued rows | left `queued` by reset? **No** — reset fails `queued` too (conservative; the client re-triggers). Simpler than partial-resume semantics. |
| Two enqueues in quick succession | both rows `queued`; worker runs them oldest-first, serially |
| `GET …/jobs/{job_id}` with a job_id from another capability | 404 (the handler checks `capability_id` match) |
| Worker thread dies (should not — every iteration is wrapped) | jobs pile up `queued`, visible via `GET …/jobs`; no crash. A future health check is out of scope. |
| `Store` write contention (worker recording a run while a request writes) | `busy_timeout=5000` + WAL — the loser waits, then proceeds |

---

## Testing

**`tests/test_storage_jobs.py`** (new)
- `enqueue_job` then `get_job` round-trips; `params` comes back as a dict.
- `capability_jobs_frame` newest-first, respects `limit`, scoped by capability.
- `claim_next_job` returns the oldest `queued`, flips it to `running` with a
  `started_at`; a second call returns the next; returns `None` when none queued.
- `finish_job` sets state/run_id/error/finished_at.
- `reset_orphaned_jobs` flips `queued`+`running` → `error`, returns the count,
  leaves `done`/`error` rows alone.
- schema `CHECK` rejects an unknown `state` on a raw insert.

**`tests/test_jobs_worker.py`** (new)
- `JobWorker(settings).drain_once()` on an empty queue → `None`.
- enqueue a job for a seeded capability → `drain_once()` → returns the job_id,
  job is `done`, `run_id` set, a `capability_runs` row exists for it.
- monkeypatch `run_capabilities` to raise → `drain_once()` → job `error`, message
  captured, `run_id` null.
- a capability that produces a failed run (e.g. pipeline raises internally, or an
  unsynced id) → job still `done`, run `status='failed'`.

**`tests/test_capability_jobs_api.py`** (new)
- `POST /capabilities/{id}/jobs` → 202, body has `job_id` + `state:"queued"`; a
  row exists.
- unknown capability → 404, no row.
- `GET /capabilities/{id}/jobs/{job_id}` → `queued`; after
  `JobWorker(settings).drain_once()` → `done` with a `run_id`.
- `GET /capabilities/{id}/jobs` → lists it; empty for a fresh capability.
- job_id under the wrong capability → 404.
- **regression:** `POST /capabilities/{id}/runs` (sync) still returns a run
  summary synchronously.

**`tests/test_jobs_lifespan.py`** (new, 1 test)
- pre-seed a `running` job row, then `with TestClient(create_app(settings,
  run_jobs=True))` → the row is `error "interrupted by restart"`. (Also
  exercises real thread start/stop.)

**Frontend** (`frontend/src/…`)
- `useJob` stops polling once `state` is terminal (mock fetch: first call
  `queued`, second `done`; assert exactly 2 calls after the interval).
- `CapabilityDetail` "Run now": mock `POST …/jobs` → `{job_id}`, then
  `GET …/jobs/{id}` → `done`; assert the toast fires and the board refetches.
- Playwright smoke: capability → **Run now (async)** → board appears.

**Full-suite gates:** `uv run ruff check src tests && uv run pytest -q` exit 0
(770 → ~790); `cd frontend && npm run test && npm run typecheck && npm run lint
&& npm run build` clean; `npm run e2e` green.

---

## File plan (for the implementation plan to expand)

| File | Change |
|---|---|
| `src/phoenix_scraper/storage.py` | `capability_jobs` schema + 2 indexes; `enqueue_job` / `get_job` / `capability_jobs_frame` / `claim_next_job` / `finish_job` / `reset_orphaned_jobs` / `_job_from_row`; `connect(timeout=5.0)` + WAL + `busy_timeout` PRAGMAs |
| `src/phoenix_scraper/jobs.py` | **new** — `JobWorker`, `_parse_dt` |
| `src/phoenix_scraper/api_capabilities.py` | `JobRequest` model; `enqueue_job` / `list_jobs` / `one_job` routes |
| `src/phoenix_scraper/api.py` | `create_app(settings, *, run_jobs=False)` + `lifespan`; `create_app_default` passes `run_jobs=True`; `app.state.job_worker` |
| `src/phoenix_scraper/cli.py` | `pheonix capability jobs <id>` |
| `CONTRACTS.md`, `README.md` | document the table, routes, worker, `run_jobs` |
| `frontend/src/api/hooks.ts` | `useJob` |
| `frontend/src/routes/CapabilityDetail.tsx` | async "Run now" |
| `frontend/e2e/smoke.spec.ts` | async run step |
| `tests/test_storage_jobs.py`, `tests/test_jobs_worker.py`, `tests/test_capability_jobs_api.py`, `tests/test_jobs_lifespan.py` | **new** |
| `frontend/src/api/hooks.test.ts(x)`, `frontend/src/routes/CapabilityDetail.test.tsx` | job hook + async Run now |

## Self-review

- **Placeholders:** none — every method and route has a body or exact signature.
- **Consistency:** `run_id` from `results[0].run.run_id` matches
  `CapabilityRunResult.run: CapabilityRun` (`run_id: str`). `JobRequest` mirrors
  the existing `RunRequest` (`from_`/`to`/`replace_today`, `populate_by_name`).
  `_frame_response(df, fmt, name)` signature matches the other list routes.
- **Scope:** one subsystem (background capability runs), one plan. No parallel
  workers, no cancellation, no scheduler — all listed as non-goals.
- **Ambiguity resolved:** restart fails `queued` rows too (not partial-resume);
  a capability-level failure ends the job `done` (not `error`); the worker is
  opt-in via `run_jobs` so no existing test changes.
- **Risk:** `PRAGMA journal_mode=WAL` on every `Store` open is the widest blast
  radius. It is standard for concurrent SQLite, local-only, and the sidecar
  files are already under the gitignored `data/`. If any test asserts on the raw
  DB file it may need a `-wal` glob — the plan's first task runs the full suite
  to catch it.
