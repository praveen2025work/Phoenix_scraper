# Ladder Close-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last three non-architectural gaps in the Capability Promotion
Ladder: harden the `capabilities` table against bad rows, bring `CONTRACTS.md` /
`README.md` back in sync with what shipped, and give the React SPA loading
skeletons, a render error boundary, table a11y, and the one missing Analytics
panel (`/insights/questions`).

**Architecture:** (1) `storage.py` gets two `CHECK` constraints on the
`capabilities` `CREATE TABLE` (new DBs) plus a defensive `_capability_from_row`
that coerces a non-positive `window_days` to 30 and an unknown `status` to
`"active"` (any DB) — so `get_capability` behind the HTTP route can never raise a
raw `pydantic.ValidationError`. (2) Docs-only edits, verified by grep + read.
(3) Frontend: a `Skeleton` primitive + a `Panel` that renders it while loading, a
hand-rolled class `ErrorBoundary` (no new dependency) wrapping the router, an
optional `<caption>` + `scope="col"` on `DataTable`, an `aria-label`'d theme
toggle (already present — verify), and a "Question types" panel in
`CoverageSection` reading the existing `/insights/questions` endpoint.

**Tech Stack:** Python 3.11+ (stdlib `sqlite3`, pydantic v2, pytest, ruff, uv);
React 19 + Vite 8 + TS 5.9 + Tailwind v4 + Vitest 5 + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-07-capability-promotion-ladder-design.md`
§7 (capability entity — `status` is `active|paused`, `window_days` positive), §12
(the SPA), and the "Deferred/future" list carried in the project memory
(`capabilities` table CHECK constraints; SPA polish; `/insights/questions` as its
own panel). Async capability runs (spec §16.4) is explicitly **out of scope** —
it is an architectural change and gets its own brainstorm + spec later.

## Global Constraints

- Backend suite at **770**; frontend at **24** Vitest + **1** Playwright smoke.
  Nothing regresses. `uv run ruff check src tests && uv run pytest -q` — exit 0;
  `cd frontend && npm run test -- --run && npx tsc --noEmit && npm run lint &&
  npm run build` — all clean.
- **All Python functions return NEW objects; type hints on every signature.**
- **TDD:** write the failing test first, watch it fail, then implement.
- `_capability_from_row` is a **read** path — it must coerce, never raise.
- No new npm dependency. The error boundary is a hand-rolled class component.
- Commit `<type>: <description>`, one per task. End every commit body with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ke9q33MQMFSK47xfqQk4WG
  ```

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/phoenix_scraper/storage.py` | modify | `capabilities` `CREATE TABLE` gains `CHECK (window_days > 0)` + `CHECK (status IN ('active','paused'))`; `_capability_from_row` coerces bad `window_days` / `status` |
| `tests/test_capability_storage.py` | modify | new `TestCapabilitySchemaGuards` — schema rejects bad raw inserts; `_capability_from_row` coerces |
| `CONTRACTS.md` | modify | `load_capability` `window_days<=0`; `run_capability_analysis` evaluate step; `n_rung2_candidates` no longer "stays 0"; `render_rung2_stub` / `promote_candidate` `<name>` = snake_case module |
| `README.md` | modify | "Daily runs" notes the CODE validators run over in-scope spans; Rung-2 stub filename note |
| `frontend/src/components/ui/skeleton.tsx` | create | shimmer primitive |
| `frontend/src/components/Panel.tsx` | modify | skeleton while loading, `aria-busy`, `role="alert"` on error |
| `frontend/src/components/ErrorBoundary.tsx` | create | class error boundary with a reset button |
| `frontend/src/App.tsx` | modify | wrap the router in `<ErrorBoundary>` |
| `frontend/src/components/DataTable.tsx` | modify | optional `label` → `<caption class="sr-only">`; `scope="col"` on `<TH>` |
| `frontend/src/routes/analytics/CoverageSection.tsx` | modify | add the "Question types" panel |
| `frontend/src/components/Panel.test.tsx` | create | loading / error / data states |
| `frontend/src/components/ErrorBoundary.test.tsx` | create | catches a throw, resets |
| `frontend/src/components/DataTable.test.tsx` | modify | `label` renders a caption |
| `frontend/src/routes/analytics/CoverageSection.test.tsx` | modify | `/insights/questions` row renders |

---

## Task 1: `capabilities` table integrity — CHECK constraints + defensive read

**Files:**
- Modify: `src/phoenix_scraper/storage.py` (the `capabilities` block of `_SCHEMA`, ~line 161; `_capability_from_row`, ~line 949)
- Test: `tests/test_capability_storage.py`

**Interfaces:**
- Consumes: `Capability` (`window_days: int = Field(default=30, gt=0)`,
  `status: Literal["active", "paused"] = "active"`), `CapabilityFilter`.
- Produces: `_capability_from_row(row) -> Capability` — unchanged signature; now
  coerces `int(row["window_days"]) <= 0` → `30` and `row["status"] not in
  ("active", "paused")` → `"active"`. Accepts anything that supports
  `row["<key>"]` (a `sqlite3.Row` or a plain `dict`).
- Schema: a fresh DB's `capabilities` table rejects `window_days <= 0` and a
  `status` outside `('active','paused')` with `sqlite3.IntegrityError`. Existing
  DBs are unchanged (`CREATE TABLE IF NOT EXISTS`) and rely on the read-path
  coercion.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_capability_storage.py` (after `class TestCapabilityCrud`):
```python
class TestCapabilitySchemaGuards:
    def test_schema_rejects_nonpositive_window_days(self, tmp_store) -> None:
        import sqlite3

        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            tmp_store._conn.execute(
                "INSERT INTO capabilities "
                "(capability_id, created_at, updated_at, window_days) "
                "VALUES ('bad', '2026-01-01', '2026-01-01', 0)"
            )

    def test_schema_rejects_unknown_status(self, tmp_store) -> None:
        import sqlite3

        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            tmp_store._conn.execute(
                "INSERT INTO capabilities "
                "(capability_id, created_at, updated_at, status) "
                "VALUES ('bad', '2026-01-01', '2026-01-01', 'wobbly')"
            )

    def test_capability_from_row_coerces_bad_values(self) -> None:
        from phoenix_scraper.storage import _capability_from_row
        row = {
            "capability_id": "x", "name": "X", "description": "",
            "filter_project": None, "filter_workflow_stage": None,
            "filter_asset_class": None, "filter_model_name": None,
            "filter_search": None, "window_days": 0,
            "thresholds_json": "{}", "status": "wobbly",
        }
        cap = _capability_from_row(row)
        assert cap.window_days == 30
        assert cap.status == "active"

    def test_capability_from_row_keeps_good_values(self) -> None:
        from phoenix_scraper.storage import _capability_from_row
        row = {
            "capability_id": "x", "name": "X", "description": "",
            "filter_project": None, "filter_workflow_stage": None,
            "filter_asset_class": None, "filter_model_name": None,
            "filter_search": None, "window_days": 14,
            "thresholds_json": "{}", "status": "paused",
        }
        cap = _capability_from_row(row)
        assert cap.window_days == 14
        assert cap.status == "paused"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_capability_storage.py -q -k SchemaGuards`
Expected: FAIL — the two `IntegrityError` tests pass nothing / raise nothing
(no CHECK yet); `test_capability_from_row_coerces_bad_values` raises
`pydantic_core.ValidationError` (window_days not > 0) instead of returning a
coerced model.

- [x] **Step 3: Add the CHECK constraints**

In `src/phoenix_scraper/storage.py`, in `_SCHEMA`, the `capabilities` table —
change these two lines:
```python
    window_days INTEGER NOT NULL DEFAULT 30,
```
to
```python
    window_days INTEGER NOT NULL DEFAULT 30 CHECK (window_days > 0),
```
and
```python
    status TEXT NOT NULL DEFAULT 'active',
```
to
```python
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
```

- [x] **Step 4: Make `_capability_from_row` coerce**

In `src/phoenix_scraper/storage.py`, replace `_capability_from_row` with:
```python
def _capability_from_row(row: sqlite3.Row) -> Capability:
    window_days = int(row["window_days"])
    status = row["status"]
    return Capability(
        id=row["capability_id"],
        name=row["name"],
        description=row["description"],
        filter=CapabilityFilter(
            project=row["filter_project"],
            workflow_stage=row["filter_workflow_stage"],
            asset_class=row["filter_asset_class"],
            model_name=row["filter_model_name"],
            search=row["filter_search"],
        ),
        window_days=window_days if window_days > 0 else 30,
        thresholds=json.loads(row["thresholds_json"]),
        status=status if status in ("active", "paused") else "active",
    )
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capability_storage.py -q`
Expected: PASS — `TestCapabilitySchemaGuards` green, `TestCapabilityCrud`
unchanged (its fixtures only ever write valid `Capability` objects).

- [x] **Step 6: Lint + full suite**

Run: `uv run ruff check src tests && uv run pytest -q`
Expected: clean; green (770 → 774). `tests/test_ladder_api.py` /
`test_capability_cli.py` unaffected — they round-trip valid capabilities only.

- [x] **Step 7: Commit**

```bash
git add src/phoenix_scraper/storage.py tests/test_capability_storage.py
git commit -m "fix: capabilities table rejects bad window_days/status; read path coerces"
```

---

## Task 2: docs sync — `CONTRACTS.md` + `README.md`

**Files:**
- Modify: `CONTRACTS.md`, `README.md`

**Interfaces:** none — documentation only. Verification is grep + a read-through.

- [x] **Step 1: `CONTRACTS.md` — `load_capability` window_days**

Find:
```
def load_capability(root: Path, cap_id: str) -> Capability
    # FileNotFoundError if absent; ValueError if not a mapping / bad YAML / bad section / bad id.
    # Unknown status -> "active". Blank filter values -> None.
```
Replace the last comment line with:
```
    # Unknown status -> "active". Blank filter values -> None.
    # window_days: absent/blank -> 30; <= 0 -> ValueError.
```

- [x] **Step 2: `CONTRACTS.md` — `run_capability_analysis` evaluate step + rung-2 count**

Find the `run_capability_analysis` doc comment:
```
    # in-scope = capability_query_filters(...); costs -> build_clusters ->
    # load_capability_skills -> match_clusters -> annotate_coverage ->
    # cluster_efficiency -> ladder.detect_rung1 -> ladder_run.update_rung1.
```
Replace with:
```
    # in-scope = capability_query_filters(...); costs ->
    # evaluate_spans + store.upsert_evaluations (when settings.evaluate_on_analyze
    # and in-scope non-empty; idempotent; a broken checker logs + adds a
    # "validation skipped" note, never aborts) -> build_clusters ->
    # load_capability_skills -> match_clusters -> annotate_coverage ->
    # cluster_efficiency -> ladder.detect_rung1/detect_rung2 ->
    # ladder_run.update_rung1/update_rung2.
```
Then find:
```
    # informational. n_rung1_candidates is set; n_rung2_candidates stays 0 (Phase D).
```
Replace with:
```
    # informational. n_rung1_candidates and n_rung2_candidates are both set.
```

- [x] **Step 3: `CONTRACTS.md` — Rung-2 artifact filenames are a snake_case module**

Find:
```
def render_rung2_stub(candidate, *, latest_observation_signals, pairs) -> [(filename, body) x3]
    # <name>.py (TEMPLATES, DECISION_TABLE when slot_stability>=0.8, handle raises
    # NotImplementedError), test_<name>.py (parametrized over pairs, ships red), <name>.md.
```
Replace with:
```
def render_rung2_stub(candidate, *, latest_observation_signals, pairs) -> [(filename, body) x3]
    # <name> = _module_name(_skill_stem(candidate)) — a valid snake_case module,
    # so test_<name>.py's `from .<name> import handle` imports. Files:
    # <name>.py (TEMPLATES, DECISION_TABLE when slot_stability>=0.8, handle raises
    # NotImplementedError), test_<name>.py (parametrized over the real observed
    # (input_text, output_text) pairs, ships red), <name>.md.
```
Then find:
```
    # rung 'deterministic' -> writes deterministic/<name>.{py,md} + test_<name>.py.
```
Replace with:
```
    # rung 'deterministic' -> writes deterministic/<name>.{py,md} + test_<name>.py
    #   (<name> snake_case; pairs are real member (input,output) via _member_pairs,
    #    falling back to (prompt, prompt) only when a cluster has no recorded members).
```

- [x] **Step 4: `README.md` — "Daily runs" mentions scoped validation**

Find (in the "## Daily runs" section):
```
for `--all`), restricts to the capability's filter and a `[from, to]` window
(default: the last `window_days`), runs the mining pipeline over just those
spans, and records the run so consecutive runs can be diffed.
```
Replace with:
```
for `--all`), restricts to the capability's filter and a `[from, to]` window
(default: the last `window_days`), runs the mining pipeline over just those
spans, runs the CODE validators over them so the quality panels reflect this
capability, and records the run so consecutive runs can be diffed.
```

- [x] **Step 5: `README.md` — Rung-2 stub is runnable**

Find (in the "## The promotion ladder" section, the Rung 2 paragraph):
```
`rung2_sustained_runs` (3) runs the `<cap>:d:<cluster>` candidate is `ready`;
`promote` writes a `deterministic/<name>.py` stub + a red `test_<name>.py` with
```
Replace with:
```
`rung2_sustained_runs` (3) runs the `<cap>:d:<cluster>` candidate is `ready`;
`promote` writes a `deterministic/<name>.py` stub (`<name>` is a snake_case
module) + a red, importable `test_<name>.py` parametrized over the real observed
`(prompt, answer)` pairs, with
```

- [x] **Step 6: Verify**

Run:
```bash
grep -n "stays 0 (Phase D)" CONTRACTS.md || echo "OK: stale rung-2 line gone"
grep -n "window_days: absent/blank -> 30" CONTRACTS.md
grep -n "runs the CODE validators over them" README.md
grep -n "importable .test_<name>.py." README.md
```
Expected: the first prints `OK:`; the rest print one match each. Then read both
diffs top to bottom once for tone/accuracy.

- [x] **Step 7: Commit**

```bash
git add CONTRACTS.md README.md
git commit -m "docs: sync CONTRACTS/README with scoped eval, real Rung-2 pairs, window_days guard"
```

---

## Task 3: SPA polish — skeletons, error boundary, table a11y, question-types panel

**Files:**
- Create: `frontend/src/components/ui/skeleton.tsx`,
  `frontend/src/components/ErrorBoundary.tsx`,
  `frontend/src/components/Panel.test.tsx`,
  `frontend/src/components/ErrorBoundary.test.tsx`
- Modify: `frontend/src/components/Panel.tsx`, `frontend/src/App.tsx`,
  `frontend/src/components/DataTable.tsx`,
  `frontend/src/routes/analytics/CoverageSection.tsx`,
  `frontend/src/components/DataTable.test.tsx`,
  `frontend/src/routes/analytics/CoverageSection.test.tsx`

**Interfaces:**
- Produces: `<Skeleton className?>` — a `div.animate-pulse.bg-muted`.
- `<Panel>` — same props (`title`, `subtitle`, `children`, `isLoading?`,
  `error?`); loading renders three `<Skeleton>` bars inside a
  `data-testid="panel-skeleton"` wrapper and sets `aria-busy` on the content;
  error renders `<p role="alert">`.
- `<ErrorBoundary>{children}</ErrorBoundary>` — class component; on a thrown
  render error shows a `role="alert"` panel with a "Try again" button that clears
  the error state.
- `<DataTable>` gains optional `label?: string` → `<caption class="sr-only">`;
  every `<TH>` gets `scope="col"`.
- `CoverageSection` gains a "Question types" `<Panel>` bound to
  `useScoped<Row[]>("qtypes", "/insights/questions", id)` — columns
  `question_type`, `count` (asks), `n_users`, `n_sessions`, `total_cost_usd`.

- [x] **Step 1: Write the failing tests**

Create `frontend/src/components/Panel.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Panel } from "./Panel";

test("shows a skeleton while loading", () => {
  render(
    <Panel title="Coverage" isLoading>
      <p>data</p>
    </Panel>,
  );
  expect(screen.getByTestId("panel-skeleton")).toBeInTheDocument();
  expect(screen.queryByText("data")).not.toBeInTheDocument();
});

test("shows the error message with an alert role", () => {
  render(
    <Panel title="Coverage" error={new Error("boom")}>
      <p>data</p>
    </Panel>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("boom");
});

test("renders children when settled", () => {
  render(
    <Panel title="Coverage">
      <p>data</p>
    </Panel>,
  );
  expect(screen.getByText("data")).toBeInTheDocument();
});
```

Create `frontend/src/components/ErrorBoundary.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom({ crash }: { crash: boolean }) {
  if (crash) throw new Error("kaboom");
  return <p>fine</p>;
}

test("catches a render error and recovers on Try again", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const { rerender } = render(
    <ErrorBoundary>
      <Boom crash />
    </ErrorBoundary>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("kaboom");

  rerender(
    <ErrorBoundary>
      <Boom crash={false} />
    </ErrorBoundary>,
  );
  await userEvent.click(screen.getByRole("button", { name: /try again/i }));
  expect(screen.getByText("fine")).toBeInTheDocument();
});
```

Append to `frontend/src/components/DataTable.test.tsx`:
```tsx
test("renders a screen-reader caption when label is given", () => {
  render(
    <DataTable
      label="Question types by frequency"
      columns={[{ key: "name", header: "Name" }]}
      rows={[{ name: "why" }]}
    />,
  );
  expect(screen.getByText("Question types by frequency")).toBeInTheDocument();
});
```

Append to `frontend/src/routes/analytics/CoverageSection.test.tsx` inside the
existing `vi.spyOn(... fetch ...)` mock implementation, add a branch:
```tsx
    if (p === "/insights/questions")
      return json([
        { question_type: "why", count: 42, n_users: 6, n_sessions: 12, total_cost_usd: 0.83 },
      ]);
```
and after the existing assertions in that test:
```tsx
  expect(screen.getByText("Question types")).toBeInTheDocument();
  expect(screen.getByText("why")).toBeInTheDocument();
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm run test -- --run Panel ErrorBoundary DataTable CoverageSection`
Expected: FAIL — `Panel.test` (no `panel-skeleton` testid, error has no `alert`
role), `ErrorBoundary.test` (module does not exist), `DataTable.test` (no
caption), `CoverageSection.test` ("Question types" not rendered).

- [x] **Step 3: Add the `Skeleton` primitive**

Create `frontend/src/components/ui/skeleton.tsx`:
```tsx
import * as React from "react";
import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />;
}
```

- [x] **Step 4: Skeleton + a11y in `Panel`**

Replace `frontend/src/components/Panel.tsx` with:
```tsx
import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

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
      <CardContent aria-busy={isLoading || undefined}>
        {isLoading ? (
          <div className="space-y-2" data-testid="panel-skeleton">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        ) : error ? (
          <p className="text-sm text-destructive" role="alert">
            {(error as Error).message}
          </p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
```

- [x] **Step 5: Add the `ErrorBoundary`**

Create `frontend/src/components/ErrorBoundary.tsx`:
```tsx
import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="mx-auto max-w-md space-y-3 p-8 text-center">
          <p className="font-semibold">Something broke rendering this view.</p>
          <p className="text-sm text-muted-foreground">{this.state.error.message}</p>
          <Button onClick={() => this.setState({ error: null })}>Try again</Button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [x] **Step 6: Wrap the router in `App.tsx`**

In `frontend/src/App.tsx`, add the import:
```tsx
import { ErrorBoundary } from "./components/ErrorBoundary";
```
and wrap the `<Suspense>` block:
```tsx
        <main className="mx-auto max-w-6xl p-6">
          <ErrorBoundary>
            <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
              <Routes>
                <Route path="/" element={<CapabilitiesIndex />} />
                <Route path="/c/:id" element={<CapabilityDetail />} />
                <Route path="/c/:id/analytics" element={<Analytics />} />
                <Route path="/c/:id/candidate/:cid" element={<CandidateDetail />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </main>
```

- [x] **Step 7: `DataTable` caption + `scope`**

In `frontend/src/components/DataTable.tsx`, add `label` to the prop type and
signature:
```tsx
export function DataTable<R extends Record<string, unknown>>({
  columns,
  rows,
  max = 25,
  label,
}: {
  columns: Column<R>[];
  rows: R[] | undefined;
  max?: number;
  label?: string;
}) {
```
Immediately inside `<Table>`, before `<THead>`:
```tsx
    <Table>
      {label ? <caption className="sr-only">{label}</caption> : null}
      <THead>
```
and give the header cell `scope`:
```tsx
            <TH key={c.key} scope="col" className={c.align === "right" ? "text-right" : ""}>
              {c.header}
            </TH>
```
(The empty-rows early return stays as is — `<p>No rows.</p>`.)

- [x] **Step 8: "Question types" panel in `CoverageSection`**

In `frontend/src/routes/analytics/CoverageSection.tsx`:
- extend the format import:
  ```tsx
  import { num, truncate, usd } from "./format";
  ```
- add the hook alongside the others:
  ```tsx
  const qtypes = useScoped<Row[]>("qtypes", "/insights/questions", id);
  ```
- add the panel as the first child of `<section>`, right after the `<h3>`:
  ```tsx
      <Panel
        title="Question types"
        subtitle="the shape of what users ask under this capability"
        isLoading={qtypes.isLoading}
        error={qtypes.error}
      >
        <DataTable
          label="Question types by frequency"
          rows={qtypes.data}
          columns={[
            { key: "question_type", header: "type" },
            { key: "count", header: "asks", align: "right", format: (v) => num(v) },
            { key: "n_users", header: "users", align: "right", format: (v) => num(v) },
            { key: "n_sessions", header: "sessions", align: "right", format: (v) => num(v) },
            { key: "total_cost_usd", header: "cost", align: "right", format: (v) => usd(v) },
          ]}
        />
      </Panel>
  ```
  (`Row` is already imported via `import { type Row, useScoped } from "@/api/hooks";`.)

- [x] **Step 9: Run the tests to verify they pass**

Run: `cd frontend && npm run test -- --run`
Expected: PASS — 24 → 29 (3 Panel + 1 ErrorBoundary + 1 DataTable; the
CoverageSection test gains assertions, not a new test). `Analytics.test.tsx`
and the other section tests still pass — `Panel`'s public contract is unchanged,
the skeleton only shows while `isLoading`.

- [x] **Step 10: Type-check, lint, build**

Run: `cd frontend && npx tsc --noEmit && npm run lint && npm run build`
Expected: all clean. (If `tsc` flags `React.HTMLAttributes` in `skeleton.tsx`,
confirm `import * as React from "react"` is present — it is in the snippet.)

- [x] **Step 11: Playwright smoke still green**

Run: `cd frontend && npm run test:e2e` (or `make ui-e2e` from the repo root —
starts the API on :8000 + Vite, runs `e2e/smoke.spec.ts`).
Expected: PASS — the smoke drives the capability → run → candidate flow; the
error boundary and skeletons don't change any of those paths.

- [x] **Step 12: Commit**

```bash
git add frontend/src/components/ui/skeleton.tsx frontend/src/components/ErrorBoundary.tsx \
  frontend/src/components/Panel.tsx frontend/src/components/Panel.test.tsx \
  frontend/src/components/ErrorBoundary.test.tsx frontend/src/App.tsx \
  frontend/src/components/DataTable.tsx frontend/src/components/DataTable.test.tsx \
  frontend/src/routes/analytics/CoverageSection.tsx \
  frontend/src/routes/analytics/CoverageSection.test.tsx
git commit -m "feat: SPA loading skeletons, render error boundary, table a11y, question-types panel"
```

---

## Self-Review

- **Spec coverage.** §7 capability entity: Task 1 makes the DB enforce what the
  `Capability` model already promises (`window_days > 0`, `status ∈
  {active,paused}`) and keeps the read path total. Memory "Deferred/future" —
  `capabilities` table CHECK constraints → Task 1; SPA polish (skeletons, error
  boundaries, a11y) → Task 3; `/insights/questions` as its own panel → Task 3
  Step 8. Async runs (§16.4) is deliberately excluded and recorded as needing
  its own design cycle.
- **`IF NOT EXISTS` caveat.** The CHECK constraints only bind fresh DBs; a
  pre-existing `pheonix.db` keeps its unconstrained `capabilities` table. This is
  acceptable because (a) the read-path coercion in Step 4 protects every DB and
  (b) local POC DBs are disposable. A full table rebuild-and-copy migration is
  not worth the risk here; noted, not done.
- **Placeholder scan.** Every code step has literal code. The doc task (Task 2)
  quotes the exact before/after text and ends with a grep gate.
- **Type consistency.** `_capability_from_row(row) -> Capability` unchanged.
  Frontend: `Panel` props unchanged; `DataTable` gains an *optional* `label` so
  all existing call sites still type-check; `ErrorBoundary` is `Component<Props,
  State>` with `getDerivedStateFromError`. `usd` already exists in
  `routes/analytics/format.ts`.
- **`question_taxonomy` columns.** `insights.question_taxonomy` returns
  `question_type, count, n_sessions, n_users, total_cost_usd` (+ more) — the five
  columns the panel reads. `/insights/questions` is an existing `@protected`
  route and honours `?capability=` via `AnalysisFiltersDep` → `_merge_capability`,
  so `useScoped` scopes it for free.
- **Ambiguity.** The error boundary does not reset on route change — "Try again"
  is the only reset. Acceptable for v1; the header `<Link>` sits outside the
  boundary so navigation always works. If this proves annoying in the smoke, a
  `key={location.pathname}` wrapper is a follow-up, not a blocker.
- **Test count.** Backend 770 → 774 (Task 1). Frontend 24 → 29 (Task 3).
