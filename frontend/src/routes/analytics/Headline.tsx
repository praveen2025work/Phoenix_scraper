import { useOverview, useRunDeltas, useScoped } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Card, CardContent } from "@/components/ui/card";
import { AreaSeriesChart } from "@/components/ui/chart";
import { num, pct, truncate, usd } from "./format";

interface ActivityRow {
  day: string;
  n_asks: number;
  total_cost_usd: number;
}

const KPIS: { key: string; label: string; fmt: (v: unknown) => string; from: "o" | "q" }[] = [
  { key: "n_spans", label: "spans", fmt: (v) => num(v), from: "o" },
  { key: "n_sessions", label: "sessions", fmt: (v) => num(v), from: "o" },
  { key: "n_users", label: "users", fmt: (v) => num(v), from: "o" },
  { key: "total_tokens", label: "tokens", fmt: (v) => num(v), from: "o" },
  { key: "total_cost_usd", label: "cost", fmt: (v) => usd(v), from: "o" },
  { key: "error_rate", label: "error rate", fmt: (v) => pct(v), from: "o" },
  { key: "span_pass_rate", label: "validation pass", fmt: (v) => pct(v), from: "q" },
  { key: "avg_latency_ms", label: "avg latency", fmt: (v) => `${num(v)} ms`, from: "o" },
];

export function Headline({ id }: { id: string }) {
  const overview = useOverview(id);
  const quality = useScoped<Record<string, number>>("qoverview", "/quality/overview", id);
  const activity = useScoped<ActivityRow[]>("activity", "/insights/activity", id);
  const deltas = useRunDeltas(id);

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        {KPIS.map((k) => {
          const src = k.from === "o" ? overview.data : quality.data;
          return (
            <Card key={k.key}>
              <CardContent className="p-3">
                <p className="text-xs text-muted-foreground">{k.label}</p>
                <p className="text-lg font-semibold tabular-nums">
                  {src ? k.fmt(src[k.key]) : "—"}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Panel
        title="Activity by day"
        subtitle="asks per day in this capability's scope"
        isLoading={activity.isLoading}
        error={activity.error}
      >
        <AreaSeriesChart
          data={(activity.data ?? []).map((a) => ({
            label: a.day.slice(5),
            value: a.n_asks,
          }))}
        />
      </Panel>

      <Panel
        title="What changed since the last run"
        isLoading={deltas.isLoading}
        error={deltas.error}
      >
        <DataTable
          rows={deltas.data}
          columns={[
            { key: "status", header: "status" },
            {
              key: "count",
              header: "prev → count",
              format: (_v, r) => `${num(r.count_prev)} → ${num(r.count)}`,
            },
            { key: "representative", header: "representative", format: (v) => truncate(v, 90) },
          ]}
        />
      </Panel>
    </section>
  );
}
