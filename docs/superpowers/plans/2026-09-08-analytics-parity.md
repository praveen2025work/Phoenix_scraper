# SPA Analytics Parity + Retire the Bundled Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bring the SPA's Analytics tab (`/c/:id/analytics`) to parity with the
legacy bundled dashboard's panels — KPI row, an activity chart, quality-by-user/
model charts, and ~14 tables — then delete `static/dashboard.html` and the
`GET /legacy` route (the spec's Phase G, finished).

**Architecture:** Every panel is a `<Panel>` card wrapping either a
`<DataTable columns rows>` or a `<Chart>` (Recharts) fed by a small TanStack
Query hook that hits an existing endpoint with `?capability=<id>` (or, for the
run-delta panel, `/capabilities/{id}/runs/delta`). A generic
`useScoped(key, path)` hook removes per-panel boilerplate. The Analytics route
is a set of `<section>`s: **Headline** (KPIs + activity + run deltas),
**Coverage & skills**, **Answer quality**, **Agent behaviour**. Then the
backend drops the HTML dashboard.

**Tech Stack:** React 19 + TanStack Query + **Recharts 3** (via a shadcn-style
`Chart` wrapper). FastAPI unchanged except removing the `/legacy` route +
`_DASHBOARD_PATH`.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
§12 screen 4 ("carried-over panels … each hitting the existing endpoints with
`?capability=:id`") and §13 Phase G ("move `static/dashboard.html` out once the
Analytics tab reaches parity; drop `GET /` HTML").

## Global Constraints

- Frontend: `cd frontend && npm run typecheck && npm test && npm run build &&
  npm run lint` — all green. Backend: `uv run ruff check src tests && uv run
  pytest -q` — exit 0, **765** tests, nothing regresses.
- Every `.tsx` file **under ~220 lines**; a panel that grows past that splits.
- **No `any`.** Endpoint rows are `Record<string, unknown>`; narrow at the cell.
- **TDD:** a failing Vitest test first for the shared components (`DataTable`,
  `Chart`, `useScoped`) and for the Analytics route (KPIs + one table + one
  chart render from mocked fetch).
- Commit `<type>: <description>`, one per task. End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```

## Endpoint → panel map (all take `?capability=<id>` unless noted)

| Panel | Endpoint | Shape |
|---|---|---|
| KPI row | `/overview` + `/quality/overview` | `{n_spans, n_sessions, n_users, total_tokens, total_cost_usd, error_rate, avg_latency_ms}` + `{span_pass_rate, n_failed_spans}` |
| Activity by day *(chart)* | `/insights/activity` | `[{day, n_asks, n_sessions, n_users, total_tokens, total_cost_usd}]` |
| What changed since last run | `/capabilities/{id}/runs/delta` *(no `?capability=`)* | `[{status, count_prev, count, representative}]` |
| Skill coverage | `/skills/coverage` | `[{skill_name, asks_routed, demonstrated, covered, …}]` |
| What to add to each skill | `/skills/updates` | `[{skill_name, source_file, n_new_prompts, uncovered_asks, n_users, yaml_block}]` |
| Proposed new skills | `/skills/gaps` | `[{proposed_name, level, capability, evidence_count, representative_prompt}]` |
| Skill health | `/insights/skill-health` | `[{skill_name, n_asks, avg_route_len, error_rate, match_score, status}]` |
| Validation scoreboard | `/quality/checks` | `[{check, target, n_evaluated, n_failed, fail_rate, avg_score, top_label, example}]` |
| Answer quality by user *(chart)* | `/quality/by?dimension=user_id` | `[{user_id, n_spans, n_failed, fail_rate, top_issues}]` |
| Answer quality by model *(chart)* | `/quality/by?dimension=model_name` | `[{model_name, n_spans, fail_rate, top_issues}]` |
| Prompt patterns answered badly | `/quality/by-prompt` | `[{representative, count, span_fail_rate, top_issues, priority}]` |
| Failed spans | `/quality/failures?top=25` | `[{span_id, user_id, model_name, workflow_stage, failed_checks, …}]` |
| Agent flows | `/insights/flows` | `[{flow, n_traces, avg_steps, avg_tokens, example_prompt}]` |
| Where the agent works too hard | `/insights/efficiency` | `[{representative, count, route_len_avg, baseline_route, long_route, tokens_per_ask, opportunity_score}]` |
| Stage × asset class | `/insights/breakdown` | `[{workflow_stage, asset_class, n_asks, n_users, total_tokens, total_cost_usd}]` |
| Tool usage | `/insights/tools` | `[{tool, n_calls, error_rate, avg_latency_ms, p95_latency_ms}]` |
| Model usage | `/insights/models` | `[{model, n_calls, total_tokens, total_cost_usd, avg_latency_ms, error_rate}]` |
| Users — who asks what | `/users` | `[{user_id, n_asks, n_sessions, n_errors, avg_route_len, total_cost_usd, top_intents}]` |

---

## Task 1: Shared building blocks — `useScoped`, `DataTable`, `Chart`

**Files:** `frontend/src/api/hooks.ts` (add `useScoped`),
`frontend/src/components/Panel.tsx`, `frontend/src/components/DataTable.tsx`,
`frontend/src/components/ui/chart.tsx`, tests.

- [x] **Step 1: `recharts` + failing tests**

```bash
cd frontend && npm install recharts@^3.10.1
```

`frontend/src/components/DataTable.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { DataTable } from "./DataTable";

test("renders headers and formatted cells, empty state when no rows", () => {
  const { rerender } = render(
    <DataTable
      columns={[
        { key: "name", header: "Name" },
        { key: "rate", header: "Fail rate", format: (v) => `${Math.round(Number(v) * 100)}%` },
      ]}
      rows={[{ name: "answer_relevance", rate: 0.05 }]}
    />,
  );
  expect(screen.getByRole("columnheader", { name: "Fail rate" })).toBeInTheDocument();
  expect(screen.getByText("5%")).toBeInTheDocument();
  rerender(<DataTable columns={[{ key: "name", header: "Name" }]} rows={[]} />);
  expect(screen.getByText(/no rows/i)).toBeInTheDocument();
});
```

`frontend/src/components/ui/chart.test.tsx`:
```tsx
import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { BarSeriesChart } from "./chart";

test("renders an svg for non-empty data", () => {
  const { container } = render(
    <BarSeriesChart data={[{ label: "a", value: 3 }, { label: "b", value: 5 }]} />,
  );
  expect(container.querySelector("svg")).toBeTruthy();
});
```

- [x] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- DataTable chart`
Expected: FAIL — modules not found.

- [x] **Step 3: `useScoped` hook**

Append to `frontend/src/api/hooks.ts`:
```ts
export type Row = Record<string, unknown>;

/** Generic scoped-analytics query: GET <path> with ?capability=<id> merged in. */
export function useScoped<T = Row[]>(key: string, path: string, capabilityId: string) {
  const sep = path.includes("?") ? "&" : "?";
  return useQuery({
    queryKey: [key, capabilityId, path],
    queryFn: () => api.get<T>(`${path}${sep}capability=${enc(capabilityId)}`),
  });
}
```

- [x] **Step 4: `Panel.tsx`**

```tsx
import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function Panel({
  title,
  subtitle,
  children,
  isLoading,
  error,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  isLoading?: boolean;
  error?: unknown;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="text-sm text-destructive">{(error as Error).message}</p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
```

- [x] **Step 5: `DataTable.tsx`**

```tsx
import type { ReactNode } from "react";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";

export interface Column<R> {
  key: string;
  header: string;
  format?: (value: unknown, row: R) => ReactNode;
  align?: "left" | "right";
}

export function DataTable<R extends Record<string, unknown>>({
  columns,
  rows,
  max = 25,
}: {
  columns: Column<R>[];
  rows: R[] | undefined;
  max?: number;
}) {
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No rows.</p>;
  }
  return (
    <Table>
      <THead>
        <TR>
          {columns.map((c) => (
            <TH key={c.key} className={c.align === "right" ? "text-right" : ""}>
              {c.header}
            </TH>
          ))}
        </TR>
      </THead>
      <TBody>
        {rows.slice(0, max).map((row, i) => (
          <TR key={i}>
            {columns.map((c) => (
              <TD key={c.key} className={c.align === "right" ? "text-right tabular-nums" : ""}>
                {c.format ? c.format(row[c.key], row) : String(row[c.key] ?? "")}
              </TD>
            ))}
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
```

- [x] **Step 6: `ui/chart.tsx`**

```tsx
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const AXIS = { fontSize: 11, stroke: "var(--color-muted-foreground)" };
const GRID = { stroke: "var(--color-border)" };

export interface Point {
  label: string;
  value: number;
}

export function BarSeriesChart({ data, height = 220 }: { data: Point[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
        <CartesianGrid vertical={false} {...GRID} />
        <XAxis dataKey="label" tick={AXIS} interval="preserveStartEnd" />
        <YAxis tick={AXIS} width={40} />
        <Tooltip
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Bar dataKey="value" fill="var(--color-primary)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AreaSeriesChart({
  data,
  height = 220,
}: {
  data: { label: string; value: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
        <CartesianGrid vertical={false} {...GRID} />
        <XAxis dataKey="label" tick={AXIS} interval="preserveStartEnd" />
        <YAxis tick={AXIS} width={40} />
        <Tooltip
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Area
          dataKey="value"
          stroke="var(--color-primary)"
          fill="var(--color-primary)"
          fillOpacity={0.15}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
```

- [x] **Step 7: Run tests + typecheck + build**

Run: `cd frontend && npm run typecheck && npm test && npm run build`
Expected: green. (Recharts renders in jsdom — `ResponsiveContainer` needs a
width; if the `svg` query is flaky, wrap the test render in a fixed-size
`<div style={{ width: 300, height: 200 }}>` and assert on
`container.querySelector("svg, .recharts-wrapper")`.)

- [x] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/api/hooks.ts \
  frontend/src/components/Panel.tsx frontend/src/components/DataTable.tsx \
  frontend/src/components/ui/chart.tsx \
  frontend/src/components/DataTable.test.tsx frontend/src/components/ui/chart.test.tsx
git commit -m "feat(frontend): DataTable, Chart (recharts), Panel, useScoped"
```

---

## Task 2: Analytics — Headline section (KPIs, activity chart, run deltas)

**Files:** `frontend/src/routes/Analytics.tsx` (rebuild),
`frontend/src/routes/analytics/Headline.tsx`, tests.

- [x] **Step 1: Failing test**

`frontend/src/routes/Analytics.test.tsx` (replace the Phase F test with a
broader one):
```tsx
import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Analytics } from "./Analytics";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

function mock(routes: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    const hit = routes[u.pathname + u.search] ?? routes[u.pathname];
    return hit === undefined ? new Response("[]", { status: 200 }) : json(hit);
  });
}

test("headline: KPIs + activity chart + run deltas render scoped", async () => {
  const spy = mock({
    "/overview?capability=fobo": { n_spans: 388, n_users: 8, error_rate: 0.02, total_cost_usd: 1.1 },
    "/quality/overview?capability=fobo": { span_pass_rate: 0.89, n_failed_spans: 42 },
    "/insights/activity?capability=fobo": [
      { day: "2026-09-06", n_asks: 12, total_cost_usd: 0.1 },
      { day: "2026-09-07", n_asks: 20, total_cost_usd: 0.2 },
    ],
    "/capabilities/fobo/runs/delta": [
      { status: "growing", count_prev: 10, count: 25, representative: "why break" },
    ],
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() => expect(screen.getByText("388")).toBeInTheDocument());
  expect(screen.getByText(/89%/)).toBeInTheDocument(); // pass rate
  expect(screen.getByText("growing")).toBeInTheDocument();
  expect(spy.mock.calls.every(([u]) =>
    !String(u).startsWith("http://localhost:8000/insights") ||
    String(u).includes("capability=fobo"))).toBe(true);
});
```

- [x] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- Analytics`
Expected: FAIL (old Analytics has no pass-rate / activity).

- [x] **Step 3: `analytics/Headline.tsx`**

`useOverview` + `useScoped("qoverview", "/quality/overview", id)` +
`useScoped("activity", "/insights/activity", id)` + `useRunDeltas(id)`.
- KPI grid (Card per metric): spans, users, tokens, cost, error rate,
  **validation pass** (`span_pass_rate` from quality overview), avg latency.
- `<Panel title="Activity by day">` → `<AreaSeriesChart data={activity.map(a =>
  ({ label: a.day.slice(5), value: a.n_asks }))} />`.
- `<Panel title="What changed since the last run">` → `<DataTable>` over the run
  deltas (status · `count_prev → count` · representative). (Keep the existing
  logic — this replaces the current bottom table.)

- [x] **Step 4: `Analytics.tsx` shell**

```tsx
import { Link, useParams } from "react-router-dom";
import { Headline } from "./analytics/Headline";
import { CoverageSection } from "./analytics/CoverageSection";
import { QualitySection } from "./analytics/QualitySection";
import { BehaviourSection } from "./analytics/BehaviourSection";

export function Analytics() {
  const { id = "" } = useParams();
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">
        <Link to={`/c/${id}`} className="text-muted-foreground hover:underline">{id}</Link>{" "}
        / analytics
      </h2>
      <Headline id={id} />
      <CoverageSection id={id} />
      <QualitySection id={id} />
      <BehaviourSection id={id} />
    </div>
  );
}
```

`CoverageSection` / `QualitySection` / `BehaviourSection` start as
`export function X({ id }: { id: string }) { return null; }` stubs (filled in
Tasks 3–5), so the route typechecks now.

- [x] **Step 5: Verify + commit**

```bash
cd frontend && npm run typecheck && npm test && npm run build && npm run lint
git add frontend/src/routes
git commit -m "feat(frontend): analytics headline — KPIs, activity chart, run deltas"
```

---

## Task 3: Analytics — Coverage & skills section

**Files:** `frontend/src/routes/analytics/CoverageSection.tsx`, test.

Four panels, each `<Panel>` + `<DataTable>` (or a details-expander for the
paste block):

| Panel | Hook | Columns |
|---|---|---|
| Skill coverage | `useScoped("cov", "/skills/coverage", id)` | skill_name · asks (`asks_routed`\|`count`) · demonstrated (`n_declared_examples`) · covered (✓) |
| What to add to each skill | `useScoped("updates", "/skills/updates", id)` | skill_name · source_file · `n_new_prompts` · `uncovered_asks` · `n_users` — row expands to a `<pre>` of `yaml_block` |
| Proposed new skills | `useScoped("gaps", "/skills/gaps", id)` | proposed_name · level · capability · `evidence_count` · representative_prompt |
| Skill health | `useScoped("health", "/insights/skill-health", id)` | skill_name · `n_asks` · `avg_route_len` (2dp) · `error_rate` (%) · status (Badge: `effective`→ready, `review`→warn) |

- [x] **Step 1: Failing test** — mock the four routes, assert one row from each
  panel renders and the yaml_block expander shows on click. Run `npm test --
  CoverageSection`, watch it fail.
- [x] **Step 2: Implement** `CoverageSection.tsx` (~180 lines; split a panel out
  if it passes 220).
- [x] **Step 3: Verify** `npm run typecheck && npm test && npm run build && npm run lint`.
- [x] **Step 4: Commit** `feat(frontend): analytics — coverage & skills panels`.

---

## Task 4: Analytics — Answer quality section

**Files:** `frontend/src/routes/analytics/QualitySection.tsx`, test.

| Panel | Hook | Render |
|---|---|---|
| Validation scoreboard | `useScoped("checks", "/quality/checks", id)` | DataTable: check · target · applied (`n_evaluated`) · failed (`n_failed`) · fail rate (%) · example (truncate 80) |
| Answer quality by user | `useScoped("qbyuser", "/quality/by?dimension=user_id", id)` | `BarSeriesChart` of `{label: user_id, value: fail_rate}` (top 12) + a DataTable with `top_issues` |
| Answer quality by model | `useScoped("qbymodel", "/quality/by?dimension=model_name", id)` | `BarSeriesChart` `{label: model_name.split(".").pop(), value: fail_rate}` + DataTable |
| Prompt patterns answered badly | `useScoped("qbyprompt", "/quality/by-prompt", id)` | DataTable: representative (truncate) · asks (`count`) · fail rate (`span_fail_rate` %) · `top_issues` · priority — sorted by priority desc |
| Failed spans | `useScoped("fails", "/quality/failures?top=25", id)` | DataTable: span_id (last 12) · user · model · stage · `failed_checks` |

- [x] **Step 1: Failing test** — mock the routes, assert a scoreboard row + a
  chart `svg` + a failed-span row. Run `npm test -- QualitySection`, watch fail.
- [x] **Step 2: Implement** `QualitySection.tsx` (split the by-user / by-model
  pair into `QualityByDimension.tsx` — a `{ dimension, label }` component reused
  twice — to stay under 220 lines).
- [x] **Step 3: Verify.**
- [x] **Step 4: Commit** `feat(frontend): analytics — answer quality panels + charts`.

---

## Task 5: Analytics — Agent behaviour section

**Files:** `frontend/src/routes/analytics/BehaviourSection.tsx`, test.

| Panel | Hook | Columns |
|---|---|---|
| Agent flows | `useScoped("flows", "/insights/flows", id)` | flow · `n_traces` · `avg_steps` (1dp) · `avg_tokens` (0dp) · example_prompt |
| Where the agent works too hard | `useScoped("eff", "/insights/efficiency", id)` | representative (truncate) · asks · route (`route_len_avg` vs `baseline_route`, both 1dp) · **long route** (Badge danger when `long_route`) · `opportunity_score` (0dp) — sorted desc |
| Stage × asset class | `useScoped("brk", "/insights/breakdown", id)` | workflow_stage · asset_class · `n_asks` · `n_users` · cost (`total_cost_usd` $) |
| Tool usage | `useScoped("tools", "/insights/tools", id)` | tool · `n_calls` · error rate (%) · `avg_latency_ms` (0dp) · `p95_latency_ms` |
| Model usage | `useScoped("models", "/insights/models", id)` | model (last segment) · `n_calls` · `total_tokens` · cost ($) · `avg_latency_ms` · error rate (%) |
| Users — who asks what | `useScoped("users", "/users", id)` | user_id · `n_asks` · `n_sessions` · `n_errors` · `avg_route_len` (2dp) · cost ($) · `top_intents` |

- [x] **Step 1: Failing test** — mock, assert one row from three of the panels.
  `npm test -- BehaviourSection`, watch fail.
- [x] **Step 2: Implement** `BehaviourSection.tsx` (a `formatters.ts` helper —
  `pct`, `usd`, `num`, `truncate`, `modelShort` — shared by all sections; put it
  in `frontend/src/routes/analytics/format.ts` and use it from Tasks 3–5).
- [x] **Step 3: Verify.**
- [x] **Step 4: Commit** `feat(frontend): analytics — agent behaviour panels`.

---

## Task 6: Retire the bundled dashboard

**Files:** `src/phoenix_scraper/api.py`, `src/phoenix_scraper/static/dashboard.html`
(delete), `tests/test_api.py`, `tests/test_insights_api.py`, `CONTRACTS.md`,
`README.md`, `MANIFEST`/`pyproject` (check for a static-file include).

- [x] **Step 1: Update the tests**

In `tests/test_api.py` — change `test_root_is_a_json_notice_not_html` to drop
the `legacy_dashboard` assertion, add `assert "legacy_dashboard" not in body`;
delete `test_legacy_dashboard_still_serves_html` and add:
```python
def test_legacy_dashboard_is_gone(client: TestClient) -> None:
    assert client.get("/legacy").status_code == 404
```
In `tests/test_insights_api.py` — delete
`test_legacy_dashboard_served_at_slash_legacy`.

- [x] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api.py -q -k legacy`
Expected: FAIL — `/legacy` still 200.

- [x] **Step 3: Remove it**

In `src/phoenix_scraper/api.py`:
- delete the `@app.get("/legacy")` route and the `legacy_dashboard` function;
- delete `_DASHBOARD_PATH` (module constant) and the now-unused `HTMLResponse`
  import if nothing else uses it (`grep HTMLResponse src/phoenix_scraper/api.py`);
- in `root()`, drop the `"legacy_dashboard"` key, keep `frontend`.
```bash
git rm src/phoenix_scraper/static/dashboard.html
rmdir src/phoenix_scraper/static 2>/dev/null || true
```
Check `pyproject.toml` / `MANIFEST.in` for a `static/` package-data include and
remove it if present (`grep -rn "static" pyproject.toml MANIFEST.in 2>/dev/null`).

- [x] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: PASS (765 → ~764: one legacy test removed, one added).

- [x] **Step 5: Lint + docs**

Run: `uv run ruff check src tests`.
- `CONTRACTS.md`: the `GET /` line loses `legacy_dashboard`; drop the
  `GET /legacy` mention; drop the `## Dashboard UI`-related note if any.
- `README.md`: replace `## Legacy dashboard` with a one-liner under
  `## Frontend (React SPA)` — "The pre-SPA bundled dashboard was removed once the
  Analytics tab reached parity (`git show <this commit>` for the last version)."
  Remove the old `## Dashboard UI` panel table entirely (it now lives in the
  SPA).

- [x] **Step 6: Full frontend + backend green**

Run: `uv run pytest -q && cd frontend && npm run typecheck && npm test && npm run build`
Expected: all green.

- [x] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: retire the bundled dashboard — the SPA Analytics tab is at parity"
```

---

## Self-Review

**Parity:** the endpoint→panel map covers every panel in the legacy dashboard's
table (KPI row, skill coverage, what-to-add, what-changed, validation, quality
by user/model, prompt patterns, failed spans, what users ask ≈ `/users`,
activity, users, agent flows, tool/model usage, stage×asset, efficiency, skill
health, proposed skills). "What users are asking" (`/insights/questions`,
intent taxonomy) is folded into the `/users` `top_intents` column rather than
its own panel — the one deliberate trim; add `/insights/questions` as a panel
later if it's missed.

**Placeholder scan:** the section stubs in Task 2 Step 4 are named and filled in
Tasks 3–5 (so the route typechecks between commits). No `TBD` in prose.

**Type consistency:** `useScoped<T>(key, path, id)` — one signature, every panel.
`Column<R>` / `DataTable<R>` generic over the row type; panels pass
`Record<string, unknown>` rows and narrow in `format`. `Point {label, value}` —
`BarSeriesChart` / `AreaSeriesChart` ↔ every chart call site. `format.ts`
helpers (`pct`, `usd`, `num`, `truncate`, `modelShort`) defined once (Task 5
Step 2), used from Tasks 3–5 — **create `format.ts` in Task 3** and import it
back-compatibly (Task 3's own commit adds it).

**Ambiguity:**
- The run-delta panel hits `/capabilities/{id}/runs/delta` (capability-native),
  NOT `/runs/delta?capability=` — `useScoped` is bypassed there, `useRunDeltas`
  (Phase F) is reused.
- Recharts in jsdom: `ResponsiveContainer` reports width 0, so charts render an
  empty `.recharts-wrapper` — tests assert the wrapper/`svg` exists, not its
  contents. Real width comes from the browser.
- `/quality/*` routes use `QualityFiltersDep` which already forwards
  `capability` (Phase E Task 5) — `useScoped` appending `?capability=` works.
- Deleting `static/dashboard.html`: confirm no test reads it by path
  (`grep -rn dashboard.html tests/`) before `git rm`.
