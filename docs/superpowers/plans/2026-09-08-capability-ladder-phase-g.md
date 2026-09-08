# Capability Promotion Ladder — Phase G (Reframe the bundled dashboard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the React SPA the primary frontend: `GET /` becomes a JSON
notice instead of serving HTML, the legacy bundled dashboard moves to
`GET /legacy` (kept — the SPA's Analytics tab is a lighter view, not full
16-panel parity), the new `Settings` fields land in `.env.example`, and
README / CONTRACTS are reframed.

**Architecture:** One route rename in `api.py` (`GET /` → JSON, `GET /legacy` →
the existing `dashboard.html`). No code removed — the spec's "legacy kept one
release" applies, and Analytics parity is not yet reached. Docs + `.env.example`.

**Tech Stack:** FastAPI, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
§12 ("API stops serving HTML — `GET /` returns a JSON notice"), §13 Phase G row,
§14 (the `rung*` / `material_change_*` Settings).

## Global Constraints

- Backend suite at **763** after Phase F; nothing regresses. `uv run pytest -q`
  (exit 0 = pass), `uv run ruff check src tests`.
- Commit `<type>: <description>`. End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```

---

## Task 1: `GET /` → JSON notice; legacy dashboard at `GET /legacy`

**Files:** `src/phoenix_scraper/api.py`, `tests/test_api.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api.py`:
```python
def test_root_is_a_json_notice_not_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "pheonix"
    assert body["legacy_dashboard"] == "/legacy"
    assert "content-type" in r.headers and "json" in r.headers["content-type"]


def test_legacy_dashboard_still_serves_html(client: TestClient) -> None:
    r = client.get("/legacy")
    assert r.status_code == 200
    assert r.text.lstrip().lower().startswith("<!doctype html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -q -k "json_notice or legacy_dashboard"`
Expected: FAIL — `GET /` returns HTML; `GET /legacy` is 404.

- [ ] **Step 3: Implement**

In `src/phoenix_scraper/api.py`, replace the `@app.get("/", ...)` route:
```python
    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": "pheonix",
            "docs": "/docs",
            "health": "/health",
            "frontend": "the React SPA in frontend/ — `make ui` (dev) or `pheonix serve-ui`",
            "legacy_dashboard": "/legacy",
        }

    @app.get("/legacy", include_in_schema=False)
    def legacy_dashboard() -> HTMLResponse:
        # The pre-SPA bundled dashboard. Kept until the SPA's Analytics tab
        # reaches panel parity; every value it shows still comes from the
        # protected endpoints below.
        return HTMLResponse(_DASHBOARD_PATH.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (763 → 765). The dashboard.html's own `fetch("/...")`
calls are all absolute-from-root, so it works unchanged at `/legacy`.

- [ ] **Step 6: Commit**

```bash
git add src/phoenix_scraper/api.py tests/test_api.py
git commit -m "feat: GET / is a JSON notice; legacy dashboard moves to /legacy"
```

---

## Task 2: `.env.example` — the ladder Settings

**Files:** `.env.example`.

- [ ] **Step 1: Add the fields**

After the existing `PHEONIX_RUN_HISTORY_LIMIT` line (or the capabilities block),
add:
```
# ladder — Rung 1 (see docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md)
PHEONIX_RUNG1_MIN_USERS=3
PHEONIX_RUNG1_MIN_COUNT=15
PHEONIX_RUNG1_SUSTAINED_RUNS=5
PHEONIX_MATERIAL_CHANGE_COUNT_FACTOR=1.5
PHEONIX_MATERIAL_CHANGE_USERS_DELTA=2
# ladder — Rung 2
PHEONIX_RUNG2_MIN_ANSWER_SPANS=10
PHEONIX_RUNG2_DETERMINISM_SCORE=0.8
PHEONIX_RUNG2_SUSTAINED_RUNS=3
```
(`PHEONIX_CORS_ORIGINS` was added in Phase E — verify it is present.)

- [ ] **Step 2: Sanity — the file still parses**

Run: `uv run python -c "from phoenix_scraper.config import load_settings; load_settings()"`
Expected: no error (blank/absent .env is fine; this just confirms no typo breaks
`Settings`).

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: .env.example — ladder rung1 / rung2 / material-change settings"
```

---

## Task 3: README + CONTRACTS reframe

**Files:** `README.md`, `CONTRACTS.md`.

- [ ] **Step 1: README**

- Rename `## Dashboard UI` → `## Legacy dashboard`, and open it with:
  > `pheonix serve` still serves the pre-SPA bundled dashboard at
  > **http://127.0.0.1:8000/legacy** (`GET /` is now a JSON notice). The
  > **[React SPA](#frontend-react-spa)** is the primary frontend; the legacy
  > dashboard stays until the SPA's Analytics tab reaches panel parity.
- In `## Quick start`, add a line pointing at `## Frontend (React SPA)`.

- [ ] **Step 2: CONTRACTS**

In the `## cli.py ... + api.py` block, change the `GET /health` line's context:
> `GET /` → JSON notice (service, docs, health, frontend, legacy_dashboard);
> `GET /legacy` → the bundled dashboard HTML; `GET /health`.

- [ ] **Step 3: Lint + full suite (docs — sanity only)**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green.

- [ ] **Step 4: Commit**

```bash
git add README.md CONTRACTS.md
git commit -m "docs: reframe — the React SPA is the frontend, /legacy is the old dashboard"
```

---

## Self-Review

- §12 "`GET /` returns a JSON notice" → Task 1. The spec's "move
  `static/dashboard.html` out" is **deferred** (documented): the SPA's Analytics
  tab is a light KPI/coverage/deltas view, not the 16-panel dashboard, so the
  file stays reachable at `/legacy`. Legacy `run_analysis` + unscoped routes are
  untouched (§13 "kept one release").
- §14 Settings → Task 2. All 8 new fields + `cors_origins`.
- No type/consistency risks — one route rename, one new route, docs.
- Ambiguity: `dashboard.html` uses root-absolute `fetch("/overview")` etc.
  (verified in Phase E), so serving it at `/legacy` needs no change to the HTML.
