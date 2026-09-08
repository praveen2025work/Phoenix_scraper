import { type Row, useScoped } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Badge } from "@/components/ui/badge";
import { modelShort, num, pct, truncate, usd } from "./format";

export function BehaviourSection({ id }: { id: string }) {
  const flows = useScoped<Row[]>("flows", "/insights/flows", id);
  const eff = useScoped<Row[]>("eff", "/insights/efficiency", id);
  const brk = useScoped<Row[]>("brk", "/insights/breakdown", id);
  const tools = useScoped<Row[]>("tools", "/insights/tools", id);
  const models = useScoped<Row[]>("models", "/insights/models", id);
  const users = useScoped<Row[]>("users", "/users", id);

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-muted-foreground">Agent behaviour</h3>

      <Panel
        title="Agent flows"
        subtitle="the step sequences the agent runs per ask"
        isLoading={flows.isLoading}
        error={flows.error}
      >
        <DataTable
          rows={flows.data}
          columns={[
            { key: "flow", header: "flow" },
            { key: "n_traces", header: "traces", align: "right", format: (v) => num(v) },
            { key: "avg_steps", header: "steps", align: "right", format: (v) => num(v, 1) },
            { key: "avg_tokens", header: "tokens", align: "right", format: (v) => num(v) },
            { key: "example_prompt", header: "example", format: (v) => truncate(v, 55) },
          ]}
        />
      </Panel>

      <Panel
        title="Where the agent works too hard"
        subtitle="long route = far more steps than the median trace — build a skill here first"
        isLoading={eff.isLoading}
        error={eff.error}
      >
        <DataTable
          rows={(eff.data ?? [])
            .slice()
            .sort((a, b) => Number(b.opportunity_score ?? 0) - Number(a.opportunity_score ?? 0))}
          columns={[
            { key: "representative", header: "pattern", format: (v) => truncate(v, 50) },
            { key: "count", header: "asks", align: "right", format: (v) => num(v) },
            {
              key: "route_len_avg",
              header: "route / baseline",
              align: "right",
              format: (v, r) => `${num(v, 1)} / ${num(r.baseline_route, 1)}`,
            },
            {
              key: "long_route",
              header: "long?",
              format: (v) => (v ? <Badge variant="danger">long</Badge> : ""),
            },
            { key: "opportunity_score", header: "opportunity", align: "right", format: (v) => num(v) },
          ]}
        />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Workflow stage × asset class"
          isLoading={brk.isLoading}
          error={brk.error}
        >
          <DataTable
            rows={brk.data}
            columns={[
              { key: "workflow_stage", header: "stage" },
              { key: "asset_class", header: "asset" },
              { key: "n_asks", header: "asks", align: "right", format: (v) => num(v) },
              { key: "n_users", header: "users", align: "right", format: (v) => num(v) },
              { key: "total_cost_usd", header: "cost", align: "right", format: (v) => usd(v) },
            ]}
          />
        </Panel>

        <Panel title="Tool usage" isLoading={tools.isLoading} error={tools.error}>
          <DataTable
            rows={tools.data}
            columns={[
              { key: "tool", header: "tool" },
              { key: "n_calls", header: "calls", align: "right", format: (v) => num(v) },
              { key: "error_rate", header: "errors", align: "right", format: (v) => pct(v) },
              { key: "avg_latency_ms", header: "avg ms", align: "right", format: (v) => num(v) },
              { key: "p95_latency_ms", header: "p95 ms", align: "right", format: (v) => num(v) },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Model usage" isLoading={models.isLoading} error={models.error}>
        <DataTable
          rows={models.data}
          columns={[
            { key: "model", header: "model", format: (v) => modelShort(v) },
            { key: "n_calls", header: "calls", align: "right", format: (v) => num(v) },
            { key: "total_tokens", header: "tokens", align: "right", format: (v) => num(v) },
            { key: "total_cost_usd", header: "cost", align: "right", format: (v) => usd(v) },
            { key: "avg_latency_ms", header: "avg ms", align: "right", format: (v) => num(v) },
            { key: "error_rate", header: "errors", align: "right", format: (v) => pct(v) },
          ]}
        />
      </Panel>

      <Panel
        title="Users — who asks what"
        subtitle="per-user asks, re-asks, errors, route length, spend, top intents"
        isLoading={users.isLoading}
        error={users.error}
      >
        <DataTable
          rows={users.data}
          columns={[
            { key: "user_id", header: "user" },
            { key: "n_asks", header: "asks", align: "right", format: (v) => num(v) },
            { key: "n_sessions", header: "sessions", align: "right", format: (v) => num(v) },
            { key: "n_errors", header: "errors", align: "right", format: (v) => num(v) },
            { key: "avg_route_len", header: "route", align: "right", format: (v) => num(v, 2) },
            { key: "total_cost_usd", header: "cost", align: "right", format: (v) => usd(v) },
            { key: "top_intents", header: "top intents" },
          ]}
        />
      </Panel>
    </section>
  );
}
