# Capability Promotion Ladder — Phase E (API surface) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose everything the SPA needs over HTTP — capability CRUD, run
trigger + history, the ladder board / candidate detail / decisions / promote —
plus an optional `?capability=` param on every existing analytics route, and a
`PHEONIX_CORS_ORIGINS` setting so a Vite dev server on another origin can call
the API.

**Architecture:** Two new route modules, each a factory returning an
`APIRouter` that is mounted under the existing `protected` router (so
`X-API-Key` + the CSRF origin guard still apply): `api_capabilities.py`
(capability CRUD + runs) and `api_ladder.py` (candidates + decisions + promote).
`create_app` gains `CORSMiddleware` bound to `settings.cors_origins`, and the
existing `security_guard` CSRF check learns to allow those origins. The scoped
`?capability=` param is added to `analysis_filters` in `api.py` — when present,
the capability's stored filter + `[now - window_days, now]` window seed the
`QueryFilters`, and any explicit query param still wins.

**Tech Stack:** Python 3.11+, FastAPI, pydantic v2, pandas, pytest (FastAPI
`TestClient`), ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
§11 (API surface), §14 (`cors_origins`). The SPA (§12) is Phase F; retiring
`dashboard.html` (§10 legacy note) is Phase G.

## Global Constraints

- Python **>= 3.11**. New route modules under **400 lines**
  (`api_capabilities.py`, `api_ladder.py`); `api.py` / `config.py` additions are
  judged on what this phase adds.
- **Type hints on every signature.** Request bodies are pydantic models
  (frozen not required for request models — FastAPI needs them mutable-parseable;
  keep them plain `BaseModel`).
- **TDD:** failing test first, watch it fail, implement.
- Module tests: `uv run pytest tests/test_<name>.py -q`. Whole suite:
  `uv run pytest -q` — **exit 0 is the pass signal; the summary line is
  suppressed, trust the exit code.** Suite is at **735** after Phase D; nothing
  that passes may regress.
- Lint: `uv run ruff check src tests` (`E, F, I, UP, B`; line length 100).
- **No network / no live Phoenix in tests.** The API test client forces
  `phoenix_endpoint=None`.
- Commit `<type>: <description>`, one per task. End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```
- Response conventions unchanged: `_frame_response(df, fmt, name)` for
  frames, `fmt=json|csv`, `X-API-Key`, the CSP + CSRF middleware.
- Phase A–D shipped: `capability.py` (`load_capability`, `load_all_capabilities`,
  `write_capability`, `scaffold_capability`, `list_capability_ids`,
  `dump_capability`, `capability_dir`); `Store` capability + run + candidate
  methods; `capability_run.run_capabilities` / `run_capability_analysis`;
  `ladder` / `ladder_run` / `determinism` / `artifacts`;
  `pheonix capability|run|candidates|candidate|decide|promote`.

---

## §11 route inventory (what this phase builds)

| Method & path | Task |
|---|---|
| `GET /capabilities` | 2 |
| `POST /capabilities` | 2 |
| `GET /capabilities/{id}` | 2 |
| `PATCH /capabilities/{id}` | 2 |
| `DELETE /capabilities/{id}` (`?purge=`) | 2 |
| `POST /capabilities/{id}/sync` | 2 |
| `POST /capabilities/{id}/runs` (`{from?, to?, replace_today?}`) | 3 |
| `GET /capabilities/{id}/runs` | 3 |
| `GET /capabilities/{id}/runs/{run_id}` | 3 |
| `GET /capabilities/{id}/runs/delta?from=&to=` | 3 |
| `GET /capabilities/{id}/candidates?rung=&status=` | 4 |
| `GET /candidates/{cid}` | 4 |
| `POST /candidates/{cid}/decision` | 4 |
| `POST /candidates/{cid}/promote?accept=` | 4 |
| `GET /candidates/{cid}/artifact/preview` | 4 |
| `?capability=` on `/overview`, `/insights/*`, `/quality/*`, `/skills/*`, `/prompts/frequent`, `/sessions`, `/costs/summary`, `/spans`, `/runs`, `/runs/delta` | 5 |
| `PHEONIX_CORS_ORIGINS` + `CORSMiddleware` + origin-guard allowance | 1 |

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/phoenix_scraper/config.py` | modify | `cors_origins: str = ""` + `cors_origin_list()` helper |
| `src/phoenix_scraper/api.py` | modify | `CORSMiddleware`; `security_guard` allows `settings.cors_origins`; mount the two new routers; `?capability=` in `analysis_filters` |
| `src/phoenix_scraper/api_capabilities.py` | **create** | `capability_router(settings)` — capability CRUD + run routes |
| `src/phoenix_scraper/api_ladder.py` | **create** | `ladder_router(settings)` — candidates / decision / promote / preview |
| `tests/test_capability_api.py` | **create** | Tasks 2–3 |
| `tests/test_ladder_api.py` | **create** | Task 4 |
| `tests/test_scoped_analytics_api.py` | **create** | Task 5 |
| `tests/test_api.py` | modify | Task 1 — CORS headers present |
| `CONTRACTS.md` / `README.md` | modify | Task 6 |

**Deferred:** no route touches the pipeline synchronously beyond what
`POST /capabilities/{id}/runs` already does (§16.4 — a job queue is the noted
follow-up). Auth is unchanged (`X-API-Key`, `actor` in bodies).

---

## Task 1: `PHEONIX_CORS_ORIGINS` + CORS middleware + origin-guard allowance

**Files:**
- Modify: `src/phoenix_scraper/config.py`
- Modify: `src/phoenix_scraper/api.py`
- Test: `tests/test_api.py` (append)

**Interfaces:**
- Produces: `Settings.cors_origins: str = ""` (comma-separated);
  `Settings.cors_origin_list() -> list[str]`.
- `create_app` adds `CORSMiddleware` (allow those origins, `allow_credentials`
  False, all methods, the `X-API-Key` + `Content-Type` headers). The
  `security_guard` CSRF check treats a request whose `Origin` is in
  `cors_origin_list()` as same-site (does not 403 it).

- [ ] **Step 1: Settings + test**

In `src/phoenix_scraper/config.py`, after `api_key`:
```python
    # Origins (comma-separated) allowed to call the API cross-site — the Vite
    # dev server in development, the deployed SPA host in production. Empty =
    # same-origin only (today's behaviour).
    cors_origins: str = ""
```
and near `skills_dir_paths`:
```python
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
```

Append to `tests/test_api.py`:
```python
def test_cors_headers_for_configured_origin(api_settings) -> None:
    from phoenix_scraper.api import create_app
    app = create_app(api_settings.model_copy(update={"cors_origins": "http://localhost:5173"}))
    with TestClient(app) as c:
        r = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
        pre = c.options(
            "/overview",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert pre.status_code in (200, 204)


def test_cross_origin_post_from_allowed_origin_is_not_csrf_blocked(api_settings) -> None:
    from phoenix_scraper.api import create_app
    app = create_app(api_settings.model_copy(update={"cors_origins": "http://localhost:5173"}))
    with TestClient(app) as c:
        c.post("/demo/seed")
        r = c.post("/analyze/run", headers={"Origin": "http://localhost:5173"})
        assert r.status_code == 200, r.text


def test_cross_origin_post_from_unknown_origin_is_csrf_blocked(api_settings) -> None:
    from phoenix_scraper.api import create_app
    with TestClient(create_app(api_settings)) as c:
        r = c.post("/analyze/run", headers={"Origin": "http://evil.example"})
        assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -q -k cors_headers or csrf`
Expected: FAIL — no `access-control-allow-origin` header.

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/api.py`, add the import:
```python
from fastapi.middleware.cors import CORSMiddleware
```
In `create_app`, right after `app.state.settings = settings`:
```python
    _cors = settings.cors_origin_list()
    if _cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["X-API-Key", "Content-Type"],
        )
```
In `security_guard`, change the cross-origin rejection to allow configured
origins:
```python
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None:
                from urllib.parse import urlsplit

                allowed = set(settings.cors_origin_list())
                same_host = urlsplit(origin).netloc == request.headers.get("host", "")
                if not same_host and origin.rstrip("/") not in allowed:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin request rejected"},
                    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (735 → ~738).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/config.py src/phoenix_scraper/api.py tests/test_api.py
git commit -m "feat: PHEONIX_CORS_ORIGINS — CORS middleware + CSRF origin allowance"
```

---

## Task 2: `api_capabilities.py` — capability CRUD routes

**Files:**
- Create: `src/phoenix_scraper/api_capabilities.py`
- Modify: `src/phoenix_scraper/api.py` (mount the router)
- Test: `tests/test_capability_api.py` (create)

**Interfaces:**
- Produces: `capability_router(settings: Settings) -> APIRouter` with the
  capability CRUD routes; mounted `protected.include_router(capability_router(settings))`
  in `create_app` before `app.include_router(protected)`.
- Request models (plain `pydantic.BaseModel`):
  - `CapabilityCreate` — `id: str`, `name: str = ""`, `description: str = ""`,
    `filter: CapabilityFilter = CapabilityFilter()`, `window_days: int = 30`,
    `thresholds: dict[str, float] = {}`.
  - `CapabilityPatch` — all optional: `name`, `description`, `filter`,
    `window_days`, `thresholds`, `status`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_api.py`:

```python
"""API tests for capability CRUD + run routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        db_path=tmp_path / "api.db", export_dir=tmp_path / "e",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
        capabilities_dir=tmp_path / "caps",
    ).model_copy(update={"phoenix_endpoint": None})
    with TestClient(create_app(settings)) as c:
        c.post("/demo/seed")
        yield c


def _create(client: TestClient, cap_id="fobo", stage="fobo_recon", **over) -> dict:
    body = {"id": cap_id, "name": cap_id.upper(),
            "filter": {"workflow_stage": stage}, "window_days": 30}
    body.update(over)
    r = client.post("/capabilities", json=body)
    assert r.status_code == 201, r.text
    return r.json()


class TestCapabilityCrud:
    def test_create_lists_and_gets(self, client: TestClient) -> None:
        _create(client)
        listing = client.get("/capabilities").json()
        assert any(c["id"] == "fobo" for c in listing)
        detail = client.get("/capabilities/fobo")
        assert detail.status_code == 200
        assert detail.json()["capability"]["filter"]["workflow_stage"] == "fobo_recon"

    def test_create_duplicate_is_409(self, client: TestClient) -> None:
        _create(client)
        r = client.post("/capabilities", json={"id": "fobo", "name": "x"})
        assert r.status_code == 409

    def test_create_bad_id_is_422_or_400(self, client: TestClient) -> None:
        r = client.post("/capabilities", json={"id": "Bad Id!", "name": "x"})
        assert r.status_code in (400, 422)

    def test_patch_updates_filter_and_status(self, client: TestClient) -> None:
        _create(client)
        r = client.patch("/capabilities/fobo",
                         json={"window_days": 14, "status": "paused"})
        assert r.status_code == 200
        got = client.get("/capabilities/fobo").json()["capability"]
        assert got["window_days"] == 14 and got["status"] == "paused"

    def test_get_missing_is_404(self, client: TestClient) -> None:
        assert client.get("/capabilities/ghost").status_code == 404

    def test_delete_removes_row_keeps_dir(self, client: TestClient, tmp_path: Path) -> None:
        _create(client)
        r = client.delete("/capabilities/fobo")
        assert r.status_code == 200
        assert client.get("/capabilities/fobo").status_code == 404
        assert (tmp_path / "caps" / "fobo" / "capability.yaml").exists()

    def test_delete_purge_removes_dir(self, client: TestClient, tmp_path: Path) -> None:
        _create(client)
        client.delete("/capabilities/fobo?purge=true")
        assert not (tmp_path / "caps" / "fobo").exists()

    def test_sync_reads_hand_edited_yaml(self, client: TestClient, tmp_path: Path) -> None:
        _create(client)
        yaml_path = tmp_path / "caps" / "fobo" / "capability.yaml"
        yaml_path.write_text(
            yaml_path.read_text().replace("window_days: 30", "window_days: 7"),
            encoding="utf-8",
        )
        r = client.post("/capabilities/fobo/sync")
        assert r.status_code == 200
        assert client.get("/capabilities/fobo").json()["capability"]["window_days"] == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_api.py -q`
Expected: FAIL — `404` on `POST /capabilities` (route not registered).

- [ ] **Step 3: Create `api_capabilities.py`**

Create `src/phoenix_scraper/api_capabilities.py`:

```python
"""Capability CRUD + run-trigger HTTP routes (mounted under the protected router)."""

import shutil
from contextlib import contextmanager
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import capability as capability_mod
from .capability_run import run_capabilities
from .config import Settings
from .models import Capability, CapabilityFilter
from .phoenix_client import PhoenixClientWrapper
from .storage import Store


class CapabilityCreate(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    filter: CapabilityFilter = Field(default_factory=CapabilityFilter)
    window_days: int = 30
    thresholds: dict[str, float] = Field(default_factory=dict)


class CapabilityPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    filter: CapabilityFilter | None = None
    window_days: int | None = None
    thresholds: dict[str, float] | None = None
    status: str | None = None


class RunRequest(BaseModel):
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    replace_today: bool = False

    model_config = {"populate_by_name": True}


def capability_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    root = settings.capabilities_dir

    @contextmanager
    def _store():
        store = Store(settings.db_path)
        try:
            yield store
        finally:
            store.close()

    def _summary(store: Store, cap: Capability) -> dict:
        runs = store.capability_runs_frame(cap.id, limit=1)
        last = runs.iloc[0].to_dict() if len(runs) else None
        cands = store.candidates_frame(cap.id)
        by = {"skill": {}, "deterministic": {}}
        for row in cands.to_dict("records"):
            by[row["rung"]][row["status"]] = by[row["rung"]].get(row["status"], 0) + 1
        return {
            "id": cap.id, "name": cap.name, "status": cap.status,
            "filter": cap.filter.model_dump(),
            "window_days": cap.window_days,
            "last_run": last, "candidates": by,
        }

    @router.get("/capabilities")
    def list_capabilities() -> list[dict]:
        with _store() as store:
            return [_summary(store, c) for c in capability_mod.load_all_capabilities(root)]

    @router.post("/capabilities", status_code=201)
    def create_capability(body: CapabilityCreate) -> dict:
        try:
            capability_mod.validate_id(body.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if capability_mod.config_path(root, body.id).exists():
            raise HTTPException(status_code=409, detail=f"Capability {body.id!r} exists")
        cap = Capability(
            id=body.id, name=body.name or body.id, description=body.description,
            filter=body.filter, window_days=body.window_days, thresholds=body.thresholds,
        )
        capability_mod.write_capability(root, cap)
        with _store() as store:
            store.upsert_capability(cap)
            return _summary(store, cap)

    @router.get("/capabilities/{cap_id}")
    def get_capability(cap_id: str) -> dict:
        try:
            cap = capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        cap_dir = capability_mod.capability_dir(root, cap_id)
        skill_files = sorted(p.name for p in (cap_dir / "skills").glob("*.md")) \
            if (cap_dir / "skills").is_dir() else []
        with _store() as store:
            return {
                "capability": cap.model_dump(),
                "summary": _summary(store, cap),
                "skill_files": skill_files,
            }

    @router.patch("/capabilities/{cap_id}")
    def patch_capability(cap_id: str, body: CapabilityPatch) -> dict:
        try:
            cap = capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
        try:
            cap = cap.model_copy(update=updates)
        except Exception as exc:  # noqa: BLE001 — pydantic validation -> 422
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        capability_mod.write_capability(root, cap)
        with _store() as store:
            store.upsert_capability(cap)
            return {"capability": cap.model_dump()}

    @router.delete("/capabilities/{cap_id}")
    def delete_capability(cap_id: str, purge: bool = Query(default=False)) -> dict:
        with _store() as store:
            removed = store.delete_capability(cap_id)
        if purge:
            shutil.rmtree(capability_mod.capability_dir(root, cap_id), ignore_errors=True)
        return {"deleted": removed, "purged": purge}

    @router.post("/capabilities/{cap_id}/sync")
    def sync_capability(cap_id: str) -> dict:
        try:
            cap = capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        with _store() as store:
            store.upsert_capability(cap)
            return {"capability": cap.model_dump()}

    _register_run_routes(router, settings, _store)
    return router
```

The `_register_run_routes` helper is **Task 3** — for now add a stub so the
module imports:
```python
def _register_run_routes(router, settings, _store):  # noqa: ANN001 — filled in Task 3
    pass
```

- [ ] **Step 4: Mount the router**

In `src/phoenix_scraper/api.py`, add near the top:
```python
from .api_capabilities import capability_router
```
In `create_app`, just before `app.include_router(protected)`:
```python
    protected.include_router(capability_router(settings))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_api.py -q -k CapabilityCrud`
Expected: PASS.

- [ ] **Step 6: File length + lint + full suite**

Run: `wc -l src/phoenix_scraper/api_capabilities.py && uv run ruff check src tests && uv run pytest -q`
Expected: under 400; clean; green (~738 → ~746).

- [ ] **Step 7: Commit**

```bash
git add src/phoenix_scraper/api_capabilities.py src/phoenix_scraper/api.py tests/test_capability_api.py
git commit -m "feat: capability CRUD API routes"
```

---

## Task 3: Run routes — trigger, history, one run, delta

**Files:**
- Modify: `src/phoenix_scraper/api_capabilities.py`
- Test: `tests/test_capability_api.py` (append)

**Interfaces:**
- Produces (inside `_register_run_routes`):
  - `POST /capabilities/{id}/runs` body `RunRequest` → runs
    `run_capabilities(store, settings, capability_ids=[id], client=<available?>,
    window_start=from, window_end=to, replace_today=...)`; returns the run
    summary (the `CapabilityRun` dict + `n_rung1_candidates` / `n_rung2_candidates`).
  - `GET /capabilities/{id}/runs?fmt=` → `store.capability_runs_frame(id)`.
  - `GET /capabilities/{id}/runs/{run_id}` → one row + parsed `notes_json`.
  - `GET /capabilities/{id}/runs/delta?from=&to=&fmt=` →
    `skill_coverage.cluster_deltas(snapshot(to or latest),
    snapshot(from or previous))`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_capability_api.py`:

```python
class TestRunRoutes:
    def test_trigger_run_records_and_returns_summary(self, client: TestClient) -> None:
        _create(client, "plex", stage="plex")
        r = client.post("/capabilities/plex/runs", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["capability_id"] == "plex"
        assert "n_rung1_candidates" in body and "n_rung2_candidates" in body
        hist = client.get("/capabilities/plex/runs").json()
        assert len(hist) == 1

    def test_one_run_detail_parses_notes(self, client: TestClient) -> None:
        _create(client, "plex", stage="plex")
        run_id = client.post("/capabilities/plex/runs", json={}).json()["run_id"]
        r = client.get(f"/capabilities/plex/runs/{run_id}")
        assert r.status_code == 200
        assert isinstance(r.json()["notes"], list)

    def test_delta_renders_after_two_runs(self, client: TestClient) -> None:
        _create(client, "plex", stage="plex")
        client.post("/capabilities/plex/runs", json={})
        client.post("/capabilities/plex/runs", json={"replace_today": False})
        r = client.get("/capabilities/plex/runs/delta")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_run_unknown_capability_is_404(self, client: TestClient) -> None:
        assert client.post("/capabilities/ghost/runs", json={}).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capability_api.py -q -k RunRoutes`
Expected: FAIL — `404` / `405` on `POST /capabilities/plex/runs`.

- [ ] **Step 3: Implement `_register_run_routes`**

Replace the stub in `src/phoenix_scraper/api_capabilities.py`:

```python
import json

from . import skill_coverage
from .capability_run import run_capabilities


def _register_run_routes(router: APIRouter, settings: Settings, _store) -> None:  # noqa: ANN001
    root = settings.capabilities_dir

    def _run_summary(row: dict) -> dict:
        out = dict(row)
        out["notes"] = json.loads(row.get("notes_json") or "[]")
        return out

    @router.post("/capabilities/{cap_id}/runs")
    def trigger_run(cap_id: str, body: RunRequest) -> dict:
        try:
            capability_mod.load_capability(root, cap_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        client = PhoenixClientWrapper(settings)
        with _store() as store:
            results = run_capabilities(
                store, settings, capability_ids=[cap_id],
                client=client if client.available() else None,
                window_start=body.from_, window_end=body.to,
                replace_today=body.replace_today,
            )
            row = store.capability_runs_frame(cap_id, limit=1).iloc[0].to_dict()
        run = results[0].run
        summary = _run_summary(row)
        summary["previous_run_id"] = results[0].previous_run_id
        summary["status"] = run.status
        return summary

    @router.get("/capabilities/{cap_id}/runs")
    def run_history(cap_id: str, fmt: str = "json") -> object:
        from .api import _frame_response
        with _store() as store:
            df = store.capability_runs_frame(cap_id)
        return _frame_response(df, fmt, "capability_runs")

    @router.get("/capabilities/{cap_id}/runs/{run_id}")
    def one_run(cap_id: str, run_id: str) -> dict:
        with _store() as store:
            df = store.capability_runs_frame(cap_id, limit=200)
        match = df[df["run_id"] == run_id]
        if match.empty:
            raise HTTPException(status_code=404, detail="No such run")
        return _run_summary(match.iloc[0].to_dict())

    @router.get("/capabilities/{cap_id}/runs/delta")
    def run_delta(
        cap_id: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None),
        fmt: str = "json",
    ) -> object:
        from .api import _frame_response
        with _store() as store:
            latest = to or store.previous_capability_run_id(cap_id)
            prev = from_ or store.previous_capability_run_id(cap_id, before=latest)
            df = skill_coverage.cluster_deltas(
                store.capability_run_snapshot_frame(cap_id, latest),
                store.capability_run_snapshot_frame(cap_id, prev),
            )
        return _frame_response(df, fmt, "capability_run_delta")
```

Move the `import json` / `from . import skill_coverage` / duplicate
`run_capabilities` import to the module's top import block (dedupe — they may
already be there from Task 2's `capability_router`; keep one copy, alphabetical).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_api.py -q`
Expected: PASS (whole file).

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~746 → ~752).

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/api_capabilities.py tests/test_capability_api.py
git commit -m "feat: capability run API routes (trigger, history, one, delta)"
```

---

## Task 4: `api_ladder.py` — candidates / decision / promote / preview

**Files:**
- Create: `src/phoenix_scraper/api_ladder.py`
- Modify: `src/phoenix_scraper/api.py` (mount)
- Test: `tests/test_ladder_api.py` (create)

**Interfaces:**
- Produces: `ladder_router(settings: Settings) -> APIRouter`, mounted under
  `protected`.
- Routes:
  - `GET /capabilities/{id}/candidates?rung=&status=&fmt=` →
    `store.candidates_frame(id, rung=, status=)`.
  - `GET /candidates/{cid}` → `{candidate, observations, decisions}` (frames as
    records; `signals_json` / `current_evidence_json` parsed).
  - `POST /candidates/{cid}/decision` body `{action, actor?, note?, snooze_runs?}`
    → applies the §10.1 transition (the same `_DECISION_TRANSITIONS` table as
    the CLI); invalid → 409 with the current status; unknown candidate → 404.
  - `POST /candidates/{cid}/promote?accept=` → `artifacts.promote_candidate`;
    returns `{paths, contents, wrote_files}`. `accept=true` allows `ready →
    promoted`.
  - `GET /candidates/{cid}/artifact/preview` → `promote_candidate(..., dry_run=True)`
    contents, nothing written.
- `_DECISION_TRANSITIONS` is lifted to a shared spot: move it from `cli.py` to
  `ladder.py` (`ladder.DECISION_TRANSITIONS`) and import it in both `cli.py` and
  `api_ladder.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ladder_api.py`:

```python
"""API tests for the ladder board / candidate / decision / promote routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
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
        c.post("/capabilities/plex/runs", json={})
        yield c


def _a_candidate(client: TestClient) -> str:
    board = client.get("/capabilities/plex/candidates").json()
    assert board, "demo plex run should yield at least one candidate"
    return board[0]["candidate_id"]


class TestBoard:
    def test_board_lists_candidates(self, client: TestClient) -> None:
        board = client.get("/capabilities/plex/candidates").json()
        assert isinstance(board, list) and board
        assert board[0]["candidate_id"].startswith("plex:")

    def test_board_filters_by_rung(self, client: TestClient) -> None:
        r = client.get("/capabilities/plex/candidates?rung=deterministic")
        assert r.status_code == 200


class TestCandidateDetail:
    def test_detail_has_observations_and_decisions(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.get(f"/candidates/{cid}")
        assert r.status_code == 200
        body = r.json()
        assert body["candidate"]["candidate_id"] == cid
        assert isinstance(body["observations"], list)
        assert isinstance(body["decisions"], list)

    def test_unknown_candidate_404(self, client: TestClient) -> None:
        assert client.get("/candidates/plex:s:nope").status_code == 404


class TestDecision:
    def test_reject_applies_transition_and_logs(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.post(f"/candidates/{cid}/decision",
                        json={"action": "reject", "actor": "alice", "note": "dupe"})
        assert r.status_code == 200, r.text
        assert client.get(f"/candidates/{cid}").json()["candidate"]["status"] == "rejected"

    def test_invalid_transition_is_409(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.post(f"/candidates/{cid}/decision",
                        json={"action": "accept", "actor": "a"})
        assert r.status_code == 409


class TestPromote:
    def test_preview_writes_nothing(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        r = client.get(f"/candidates/{cid}/artifact/preview")
        assert r.status_code == 200
        assert r.json()["contents"]
        assert client.get(f"/candidates/{cid}").json()["candidate"]["status"] != "promoted"

    def test_promote_with_accept_from_ready_needs_ready(self, client: TestClient) -> None:
        cid = _a_candidate(client)
        # brand-new candidate: promote should 409 without an accepted status
        r = client.post(f"/candidates/{cid}/promote")
        assert r.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder_api.py -q`
Expected: FAIL — `404` on `/capabilities/plex/candidates`.

- [ ] **Step 3: Move `DECISION_TRANSITIONS` to `ladder.py`**

In `src/phoenix_scraper/ladder.py`, near the top-level constants, add:
```python
DECISION_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "accept": (frozenset({"ready"}), "accepted"),
    "reject": (frozenset({"accumulating", "ready", "new"}), "rejected"),
    "snooze": (frozenset({"accumulating", "ready", "new"}), "snoozed"),
    "reopen": (frozenset({"rejected", "snoozed", "stale"}), "accumulating"),
}
```
In `src/phoenix_scraper/cli.py`, replace the local `_DECISION_TRANSITIONS` dict
with `from .ladder import DECISION_TRANSITIONS as _DECISION_TRANSITIONS` (keep
the alias so the rest of `decide` is untouched).

- [ ] **Step 4: Create `api_ladder.py`**

Create `src/phoenix_scraper/api_ladder.py`:

```python
"""Ladder board / candidate / decision / promote HTTP routes."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import artifacts, capability as capability_mod
from .config import Settings
from .ladder import DECISION_TRANSITIONS
from .storage import Store


class DecisionBody(BaseModel):
    action: str
    actor: str | None = None
    note: str = ""
    snooze_runs: int = 3


def ladder_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    root = settings.capabilities_dir

    @contextmanager
    def _store():
        store = Store(settings.db_path)
        try:
            yield store
        finally:
            store.close()

    @router.get("/capabilities/{cap_id}/candidates")
    def board(
        cap_id: str,
        rung: str | None = Query(default=None),
        status: str | None = Query(default=None),
        fmt: str = "json",
    ) -> object:
        from .api import _frame_response
        with _store() as store:
            df = store.candidates_frame(cap_id, rung=rung, status=status)
        return _frame_response(df, fmt, "candidates")

    @router.get("/candidates/{cid}")
    def candidate_detail(cid: str) -> dict:
        with _store() as store:
            c = store.get_candidate(cid)
            if c is None:
                raise HTTPException(status_code=404, detail="No such candidate")
            obs = store.candidate_observations_frame(cid)
            decisions = store.candidate_decisions_frame(cid)
        obs_records = json.loads(obs.to_json(orient="records"))
        for row in obs_records:
            row["signals"] = json.loads(row.pop("signals_json", "{}") or "{}")
        return {
            "candidate": c.model_dump(mode="json"),
            "observations": obs_records,
            "decisions": json.loads(decisions.to_json(orient="records")),
        }

    @router.post("/candidates/{cid}/decision")
    def decide(cid: str, body: DecisionBody) -> dict:
        who = body.actor or settings.operator_name or "unknown"
        if body.action not in DECISION_TRANSITIONS:
            raise HTTPException(status_code=422, detail=f"Unknown action {body.action!r}")
        allowed, target = DECISION_TRANSITIONS[body.action]
        now = datetime.now(UTC)
        with _store() as store:
            c = store.get_candidate(cid)
            if c is None:
                raise HTTPException(status_code=404, detail="No such candidate")
            if c.status not in allowed:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot {body.action} from status {c.status!r}",
                )
            store.record_candidate_decision_now(cid, body.action, who, now, note=body.note)
            updates: dict = {"status": target, "decided_by": who, "decided_at": now}
            if body.action == "reject":
                updates["dismiss_reason"] = body.note
                updates["current_evidence"] = {
                    **c.current_evidence,
                    "count_at_rejection": c.current_evidence.get("count", 0),
                    "n_users_at_rejection": c.current_evidence.get("n_users", 0),
                }
            if body.action == "snooze":
                ordinal = store.capability_run_ordinal(c.capability_id)
                updates["snooze_until_run"] = ordinal + body.snooze_runs
            store.upsert_candidate(c.model_copy(update=updates))
        return {"candidate_id": cid, "from": c.status, "to": target, "actor": who}

    def _promote(cid: str, *, accept: bool, dry_run: bool) -> dict:
        who = settings.operator_name or "api"
        now = datetime.now(UTC)
        with _store() as store:
            c = store.get_candidate(cid)
            if c is None:
                raise HTTPException(status_code=404, detail="No such candidate")
            if c.status == "ready" and accept and not dry_run:
                c = c.model_copy(update={"status": "accepted"})
                store.upsert_candidate(c)
            if c.status != "accepted" and not dry_run:
                raise HTTPException(
                    status_code=409, detail=f"Candidate is {c.status!r}; accept it first"
                )
            try:
                cap = capability_mod.load_capability(root, c.capability_id)
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            result = artifacts.promote_candidate(
                store, cap, c, now=now, actor=who, settings=settings, dry_run=dry_run,
            )
        return {
            "paths": list(result.paths),
            "contents": [{"path": p, "body": b} for p, b in result.contents],
            "wrote_files": result.wrote_files,
        }

    @router.post("/candidates/{cid}/promote")
    def promote(cid: str, accept: bool = Query(default=False)) -> dict:
        return _promote(cid, accept=accept, dry_run=False)

    @router.get("/candidates/{cid}/artifact/preview")
    def preview(cid: str) -> dict:
        return _promote(cid, accept=False, dry_run=True)

    return router
```

- [ ] **Step 5: Mount the router**

In `api.py`: `from .api_ladder import ladder_router`; and before
`app.include_router(protected)`:
`protected.include_router(ladder_router(settings))`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ladder_api.py -q`
Expected: PASS.

- [ ] **Step 7: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~752 → ~764). `tests/test_candidate_cli.py` must still
pass (the `_DECISION_TRANSITIONS` move is behaviour-preserving).

- [ ] **Step 8: Commit**

```bash
git add src/phoenix_scraper/api_ladder.py src/phoenix_scraper/api.py \
  src/phoenix_scraper/ladder.py src/phoenix_scraper/cli.py tests/test_ladder_api.py
git commit -m "feat: ladder API routes — board, candidate, decision, promote, preview"
```

---

## Task 5: Scoped `?capability=` on the analytics routes

**Files:**
- Modify: `src/phoenix_scraper/api.py`
- Test: `tests/test_scoped_analytics_api.py` (create)

**Interfaces:**
- `analysis_filters` (and therefore every route using `AnalysisFiltersDep`)
  gains `capability: str | None = None`. When set, the capability's stored
  filter (`project`, `workflow_stage`, `asset_class`, `model_name`, `search`)
  and a `[now - window_days, now]` window seed the `QueryFilters` — but an
  explicit query param (`stage`, `start`, …) still wins. Unknown capability →
  the filter is a no-op merge (routes stay 200 with an empty result), matching
  "behaviour byte-for-byte as today when absent" for the not-found case being
  lenient. `span_filters` and `quality_filters` get the same treatment via a
  shared `_merge_capability(qf, capability_id, store) -> QueryFilters`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoped_analytics_api.py`:

```python
"""The optional ?capability= param on the analytics routes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phoenix_scraper.api import create_app
from phoenix_scraper.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
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
        yield c


def test_overview_scoped_to_capability_is_a_subset(client: TestClient) -> None:
    whole = client.get("/overview").json()
    scoped = client.get("/overview?capability=plex").json()
    assert scoped["n_spans"] <= whole["n_spans"]
    assert scoped["n_spans"] > 0  # demo has plex traffic


def test_explicit_stage_overrides_capability(client: TestClient) -> None:
    a = client.get("/overview?capability=plex&stage=fobo_recon").json()
    b = client.get("/overview?stage=fobo_recon").json()
    assert a["n_spans"] == b["n_spans"]


def test_absent_capability_is_unchanged(client: TestClient) -> None:
    assert client.get("/overview").json() == client.get("/overview?capability=").json()


def test_spans_route_scopes_too(client: TestClient) -> None:
    scoped = client.get("/spans?capability=plex").json()
    assert all(row["workflow_stage"] == "plex" for row in scoped)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scoped_analytics_api.py -q`
Expected: FAIL — `?capability=plex` is ignored, `scoped == whole`.

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/api.py`, add a helper near `_utc` at module scope:
```python
def _merge_capability(qf: QueryFilters, capability_id: str | None, store: Store) -> QueryFilters:
    """Seed a QueryFilters from a stored capability; explicit fields still win."""
    if not capability_id:
        return qf
    cap = store.get_capability(capability_id)
    if cap is None:
        return qf
    from datetime import timedelta

    now = datetime.now(UTC)
    f = cap.filter
    return qf.model_copy(update={
        "project": qf.project or f.project,
        "workflow_stage": qf.workflow_stage or f.workflow_stage,
        "asset_class": qf.asset_class or f.asset_class,
        "model_name": qf.model_name or f.model_name,
        "search": qf.search or f.search,
        "start": qf.start or (now - timedelta(days=cap.window_days)),
        "end": qf.end or now,
    })
```
Give `span_filters` a `capability: str | None = None` parameter (last, before
`limit`) and, at its end, instead of returning the `QueryFilters` directly:
```python
        qf = QueryFilters(project=project, start=_utc(start), end=_utc(end),
                          workflow_stage=stage, asset_class=asset_class,
                          model_name=model_name, session_id=session_id,
                          user_id=user_id, search=search, limit=limit)
        if capability:
            with open_store() as store:
                qf = _merge_capability(qf, capability, store)
        return qf
```
`analysis_filters` and `quality_filters` forward `capability` to `span_filters`
(add the parameter to each and pass it through).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_scoped_analytics_api.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (~764 → ~768). Every existing API test must still pass —
`capability` defaults to None so absent-param behaviour is byte-for-byte.

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/api.py tests/test_scoped_analytics_api.py
git commit -m "feat: optional ?capability= param on the analytics routes"
```

---

## Task 6: Docs — CONTRACTS.md + README.md

**Files:**
- Modify: `CONTRACTS.md`
- Modify: `README.md`

- [ ] **Step 1: CONTRACTS.md**

In the `## cli.py ... + api.py` block, under `API routes:`, append the new
routes:
```
Capabilities: GET/POST /capabilities, GET/PATCH/DELETE /capabilities/{id}
(?purge=), POST /capabilities/{id}/sync.
Runs: POST /capabilities/{id}/runs {from?,to?,replace_today?}, GET
/capabilities/{id}/runs, GET /capabilities/{id}/runs/{run_id}, GET
/capabilities/{id}/runs/delta?from=&to=.
Ladder: GET /capabilities/{id}/candidates?rung=&status=, GET /candidates/{cid},
POST /candidates/{cid}/decision {action,actor?,note?,snooze_runs?} (409 on
invalid transition), POST /candidates/{cid}/promote?accept=, GET
/candidates/{cid}/artifact/preview.
Every analytics route (/overview, /insights/*, /quality/*, /skills/*,
/prompts/frequent, /sessions, /costs/summary, /spans, /runs, /runs/delta) takes
an optional ?capability=<id> that seeds the filter + [now-window_days, now]
window; explicit params win.
```
Add a `## api_capabilities.py` / `## api_ladder.py` one-liner:
```
## api_capabilities.py / api_ladder.py
def capability_router(settings) -> APIRouter   # capability CRUD + run routes
def ladder_router(settings) -> APIRouter       # board / candidate / decision / promote
# both mounted under the protected (X-API-Key) router in create_app.
```
Note the new `Settings.cors_origins` (`PHEONIX_CORS_ORIGINS`, comma-separated).
Move `DECISION_TRANSITIONS` mention into the `## ladder.py` block.

- [ ] **Step 2: README.md**

In `## API (downloadable, filterable)`, add a short paragraph:

> Capability + ladder routes mirror the CLI: `GET/POST /capabilities`,
> `POST /capabilities/{id}/runs`, `GET /capabilities/{id}/candidates`,
> `POST /candidates/{cid}/decision`, `POST /candidates/{cid}/promote`. Every
> analytics route also takes `?capability=<id>` to scope it to that capability's
> filter and window. Set `PHEONIX_CORS_ORIGINS=http://localhost:5173` (comma-
> separated) to let a separate frontend dev server call the API.

- [ ] **Step 3: Lint + full suite (docs — sanity only)**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 4: Commit**

```bash
git add CONTRACTS.md README.md
git commit -m "docs: capability / ladder API routes + CORS — CONTRACTS + README"
```

---

## Self-Review

**1. Spec coverage (§11):** every row of the §11 route inventory maps to Task
2/3/4; `?capability=` to Task 5; `PHEONIX_CORS_ORIGINS` + origin guard to Task 1.
`GET /capabilities/{id}` returns yaml contents + last-run summary + skill-file
list (§11) — Task 2's `get_capability`. `POST /candidates/{cid}/promote?accept=`
allows `ready → promoted` (§10.1) — Task 4's `_promote`.

**2. Placeholder scan:** the Task 2 `_register_run_routes` stub is a **named,
intentional** two-line placeholder filled in Task 3 (the module must import
between tasks). No `TBD` in prose; every route body is literal.

**3. Type consistency:**
- `capability_router(settings) -> APIRouter` / `ladder_router(settings) ->
  APIRouter` — defined in Task 2/4, mounted in Task 2/4's api.py edit. ✓
- `RunRequest` (`from_` aliased `from`, `to`, `replace_today`) — Task 2 model ↔
  Task 3 `trigger_run` reads (`body.from_`, `body.to`, `body.replace_today`) ↔
  Task 3 test (`json={}` and `{"replace_today": False}`). ✓
- `DecisionBody` ↔ `DECISION_TRANSITIONS` (moved to `ladder.py` in Task 4,
  imported by both `cli.py` and `api_ladder.py`). ✓
- `_merge_capability(qf, capability_id, store)` — Task 5 def ↔ Task 5
  `span_filters` call. Uses `store.get_capability` (Phase A) + `cap.filter` +
  `cap.window_days`. ✓
- `artifacts.promote_candidate(store, cap, c, *, now, actor, settings, dry_run)`
  — Phase C/D signature ↔ Task 4 `_promote` call. ✓
- `_frame_response(df, fmt, name)` imported into the route modules from
  `.api` — a late import inside the handler to avoid a circular import at module
  load (`api` imports `api_capabilities`/`api_ladder`, not the reverse at import
  time). ✓

**4. Ambiguity resolved:**
- **Circular imports.** `api.py` imports the two router factories at module top;
  the router modules import `_frame_response` **lazily inside handlers** (not at
  module top), so `import phoenix_scraper.api` → `import api_capabilities` does
  not recurse. `api_ladder` imports `ladder.DECISION_TRANSITIONS` (safe — no
  cycle).
- **Unknown capability on `?capability=`.** `_merge_capability` returns the
  filters unchanged (no 404) — the analytics routes never 404 today and the SPA
  passes a capability it just listed. A wrong id degrades to the global view,
  which is a safe, visible failure.
- **`POST /capabilities/{id}/runs` and Phoenix.** Uses the same
  `client if client.available() else None` pattern as `pheonix run` — offline in
  tests, a run note, `status` may be `partial`. The route still returns 200 with
  the summary.
- **`DELETE` idempotency.** `store.delete_capability` returns False for an absent
  row; the route still 200s with `{"deleted": false}` — DELETE is idempotent.
- **Request models are `BaseModel`, not `_Frozen`.** FastAPI parses request
  bodies into these; they are never mutated after parsing, and frozen adds
  nothing here while complicating `model_config`.
