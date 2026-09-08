import { Link, useParams } from "react-router-dom";
import { useCoverage, useOverview, useRunDeltas } from "@/api/hooks";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";

const KPI_KEYS: [string, string][] = [
  ["n_spans", "spans"],
  ["n_sessions", "sessions"],
  ["n_users", "users"],
  ["total_tokens", "tokens"],
  ["error_rate", "error rate"],
  ["pass_rate", "validation pass"],
];

export function Analytics() {
  const { id = "" } = useParams();
  const overview = useOverview(id);
  const coverage = useCoverage(id);
  const deltas = useRunDeltas(id);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">
        <Link to={`/c/${id}`} className="text-muted-foreground hover:underline">
          {id}
        </Link>{" "}
        / analytics
      </h2>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {KPI_KEYS.map(([key, label]) => {
          const v = overview.data?.[key];
          return (
            <Card key={key}>
              <CardContent className="p-3">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="text-lg font-semibold">
                  {v == null ? "—" : typeof v === "number" ? fmt(key, v) : String(v)}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Skill coverage</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <THead>
              <TR>
                <TH>skill</TH>
                <TH>asked</TH>
                <TH>demonstrated</TH>
                <TH>covered</TH>
              </TR>
            </THead>
            <TBody>
              {(coverage.data ?? []).map((row, i) => (
                <TR key={i}>
                  <TD>{String(row.skill_name ?? "")}</TD>
                  <TD>{String(row.asks_routed ?? row.count ?? "")}</TD>
                  <TD>{String(row.n_declared_examples ?? "")}</TD>
                  <TD>{row.covered ? "✓" : ""}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {coverage.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">No coverage rows.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">What changed since the last run</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <THead>
              <TR>
                <TH>status</TH>
                <TH>prev → count</TH>
                <TH>representative</TH>
              </TR>
            </THead>
            <TBody>
              {(deltas.data ?? []).map((row, i) => (
                <TR key={i}>
                  <TD>{String(row.status ?? "")}</TD>
                  <TD>
                    {String(row.count_prev ?? 0)} → {String(row.count ?? 0)}
                  </TD>
                  <TD className="max-w-md truncate">{String(row.representative ?? "")}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {deltas.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No movement (or fewer than two runs).
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function fmt(key: string, v: number): string {
  if (key.endsWith("_rate")) return `${Math.round(v * 100)}%`;
  return v.toLocaleString();
}
