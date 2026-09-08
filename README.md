# pheonix — Phoenix Prompt Miner (POC)

Scrapes **Arize Phoenix** observability data (traces, spans, sessions, prompts,
token cost), validates what the LLM answered and what users asked, finds the
**most frequently asked prompts**, matches them to your **skills catalog**, and
runs a two-rung **promotion ladder** that proposes new skills and, when a cluster
is deterministic enough, a code replacement for the LLM step.

Everything runs against a **local SQLite file + filesystem exports** — no external
services. Live Phoenix scraping is optional and env-gated.

## Repository layout

```
backend/     Python service — scraper, miner, promotion ladder, Typer CLI, FastAPI API
             └─ its own uv project (pyproject.toml, .venv, tests, config, .env)
frontend/    React 19 + Vite + TypeScript SPA — the capability & ladder UI
             └─ its own npm package (package.json, node_modules)
docs/        design specs + implementation plans (docs/superpowers/)
Makefile     thin wrappers that cd into backend/ or frontend/
```

Each half is self-contained and has its own README:

- **[backend/README.md](backend/README.md)** — install, the CLI, the API, live
  Phoenix + TLS setup, the mining/validation/ladder model, config reference.
- **[frontend/README.md](frontend/README.md)** — the SPA: dev server, build,
  tests, environment, the four screens.

## How the two work together

```
┌─────────────────┐         HTTP + JSON (CORS)          ┌──────────────────────┐
│  frontend/ SPA  │ ──────────────────────────────────▶ │  backend/ FastAPI API │
│  :5173 (Vite)   │   X-API-Key header (when a key is    │  :8000                │
│                 │   configured; kept in sessionStorage)│  + job worker thread  │
└─────────────────┘ ◀────────────────────────────────── └──────────────────────┘
                     202 {job_id} → poll GET .../jobs/{id}          │
                                                                    ▼
                                                         backend/data/pheonix.db
```

- **Transport.** The SPA calls the API by **absolute URL** — `VITE_API_BASE`
  (default `http://localhost:8000`). Because the origins differ (`:5173` vs
  `:8000`), the API must allow the SPA origin: set
  `PHEONIX_CORS_ORIGINS=http://localhost:5173` (the `make api` target does this
  for you).
- **Auth.** If `PHEONIX_API_KEY` is set on the backend, the SPA prompts for it
  once and sends it as `X-API-Key` on every request. With no key the API is open
  on loopback.
- **Long runs.** "Run now" in the SPA does **not** block: it `POST`s
  `/capabilities/{id}/jobs` → `202 {job_id}`, then polls
  `GET /capabilities/{id}/jobs/{job_id}` every 1.5 s until `state` is `done` or
  `error`. A single worker thread inside the API process drains the job queue one
  run at a time (`backend/src/phoenix_scraper/jobs.py`).
- **Types.** `make ui-types` regenerates `frontend/src/api/schema.ts` from the
  live FastAPI OpenAPI schema, so the SPA's request/response types track the API.
- **Production.** `make ui-build` then
  `cd backend && uv run pheonix serve-ui --dist ../frontend/dist` — the backend
  serves the built SPA (with deep-link fallback) alongside the API.

## Run it

Two independent apps, two terminals. Each is **two commands**.

**Backend** — Python API + background job worker, `http://localhost:8000`:

```bash
cd backend
pip install -e .          # deps + the `pheonix` command   (Python 3.11+)
pheonix serve
```
(No editable install? `pip install -r requirements.txt && python run.py`.)

**Frontend** — React SPA, `http://localhost:5173`:

```bash
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173**. `npm run dev` proxies nothing — it calls the
API at `http://localhost:8000` directly, and `pheonix serve` already allows that
origin.

**Sample data:** the store starts empty — `cd backend && pheonix demo` seeds
synthetic traffic. Or create a capability in the SPA and hit "Run now".

### Or use the Makefile (needs `uv`)

`make setup` · `make api` · `make ui` · `make test` · `make lint` ·
`make ui-test` · `make ui-e2e` · `make ui-build` · `make ui-types` · `make stack`
— thin wrappers over the commands above. See `backend/README.md` and
`frontend/README.md` for everything else.

## POC limitations (deliberate)

- Clustering is lexical (normalize + rapidfuzz), not embedding-based.
- Validation is code-only — no bundled LLM judge; `answer_relevance` /
  `answer_groundedness` are proxies (limits in `backend/README.md`).
- Cost falls back to `backend/config/pricing.yaml` (illustrative rates).
- Single-writer SQLite (WAL + `busy_timeout`); fine for a POC, one job at a time.
