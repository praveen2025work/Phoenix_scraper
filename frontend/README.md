# pheonix frontend — Capability & Ladder SPA

React 19 + Vite 8 + TypeScript 5.9 + Tailwind v4 + shadcn-style components
(Radix + CVA), TanStack Query v5, React Router 7, Recharts 3. Vitest + Testing
Library for units, Playwright for the smoke.

It drives the capability + promotion-ladder loop against the headless
[`backend/`](../backend/README.md) API. The two run as **independent processes**.

## Install & run

```bash
npm install          # first run only
npm run dev           # http://localhost:5173   (or `make ui` from the repo root)
```

The dev server expects the backend on `http://localhost:8000` with CORS open to
`http://localhost:5173`. From the repo root, `make api` starts it that way; by
hand:

```bash
cd ../backend
PHEONIX_CORS_ORIGINS=http://localhost:5173 \
  uv run uvicorn --factory phoenix_scraper.api:create_app_default --port 8000
```

## Scripts

| Command | |
| --- | --- |
| `npm run dev` | Vite dev server, HMR |
| `npm run build` | type-check + production build → `dist/` |
| `npm run preview` | serve the built `dist/` locally |
| `npm run test` | Vitest (unit) |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint |
| `npm run e2e` | Playwright smoke — boots the real backend + this dev server |

From the repo root: `make ui`, `make ui-build`, `make ui-test`, `make ui-e2e`,
`make ui-types`.

## Environment

| File | Var | Default | When |
| --- | --- | --- | --- |
| `frontend/.env` | `VITE_API_BASE` | `http://localhost:8000` | API on a different host/port — `cp .env.example .env` and edit |

Baked in at **build time** — rebuild after changing it.

Auth: if the backend sets `PHEONIX_API_KEY`, the app shows a one-time key prompt
(`ApiKeyGate`) and stores the value in `sessionStorage`; every request then
carries it as `X-API-Key`. With no backend key the app runs open.

## How it talks to the backend

- **Absolute URLs.** `src/api/client.ts` prefixes every path with `VITE_API_BASE`
  and attaches `X-API-Key`. Errors surface as `ApiError(status, detail)`.
- **Queries.** `src/api/hooks.ts` wraps the API in TanStack Query hooks
  (`useCapability`, `useCandidates`, `useScoped`, …).
- **Async runs.** "Run now" calls `useEnqueueRun` → `POST /capabilities/{id}/jobs`
  → `202 {job_id}`; `useJob(id, jobId)` then polls
  `GET /capabilities/{id}/jobs/{job_id}` every 1.5 s until `state` is `done` /
  `error`, then toasts and refetches the board.
- **Types.** `src/api/schema.ts` is generated from the backend's OpenAPI schema —
  regenerate with `make ui-types` (repo root) after changing an API route.

## Screens

| Route | |
| --- | --- |
| `/` | capabilities index + "New capability" dialog |
| `/c/:id` | capability detail — Run now, run summary, Rung 1 / Rung 2 lane boards |
| `/c/:id/candidate/:cid` | candidate detail — evidence trend, determinism signals, decide, artifact preview + promote |
| `/c/:id/analytics` | ~18 panels scoped to the capability — KPI row, activity + quality charts (Recharts, lazy-loaded), coverage, skills, agent behaviour |

Shared building blocks: `components/Panel.tsx` (card + loading skeleton + error
state), `components/DataTable.tsx` (`Column<R>` config), `components/ui/*`
(button/card/badge/tabs/dialog/input/table/chart/skeleton),
`components/ErrorBoundary.tsx` (wraps the router).

## Production

```bash
npm run build                                        # → dist/
cd ../backend && uv run pheonix serve-ui --dist ../frontend/dist
```

`serve-ui` serves the static bundle with SPA fallback for deep links. Point it at
the same origin as the API (or keep `VITE_API_BASE` + CORS for a split deploy).
