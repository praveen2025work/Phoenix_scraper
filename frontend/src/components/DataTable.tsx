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
              <TD
                key={c.key}
                className={c.align === "right" ? "text-right tabular-nums" : ""}
              >
                {c.format ? c.format(row[c.key], row) : String(row[c.key] ?? "")}
              </TD>
            ))}
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
