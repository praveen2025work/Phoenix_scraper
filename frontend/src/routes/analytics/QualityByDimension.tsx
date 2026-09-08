import { type Row, useScoped } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { BarSeriesChart } from "@/components/ui/chart";
import { modelShort, num, pct } from "./format";

export function QualityByDimension({
  id,
  dimension,
  title,
}: {
  id: string;
  dimension: "user_id" | "model_name";
  title: string;
}) {
  const q = useScoped<Row[]>(`qby-${dimension}`, `/quality/by?dimension=${dimension}`, id);
  const rows = q.data ?? [];
  const chart = rows
    .slice(0, 12)
    .map((r) => ({
      label:
        dimension === "model_name"
          ? modelShort(r[dimension])
          : String(r[dimension] ?? ""),
      value: Number(r.fail_rate ?? 0),
    }));

  return (
    <Panel title={title} subtitle="fail rate + top issue kinds" isLoading={q.isLoading} error={q.error}>
      {chart.length > 0 && <BarSeriesChart data={chart} height={180} />}
      <div className="mt-3">
        <DataTable
          rows={rows}
          columns={[
            { key: dimension, header: dimension.replace("_", " "), format: (v) => (dimension === "model_name" ? modelShort(v) : String(v ?? "")) },
            { key: "n_spans", header: "spans", align: "right", format: (v) => num(v) },
            { key: "fail_rate", header: "fail rate", align: "right", format: (v) => pct(v) },
            { key: "top_issues", header: "top issues", format: (v) => String(v ?? "—") },
          ]}
        />
      </div>
    </Panel>
  );
}
