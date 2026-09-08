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

const AXIS = { fontSize: 11, fill: "var(--color-muted-foreground)" };
const GRID = { stroke: "var(--color-border)" };
const TOOLTIP = {
  contentStyle: {
    background: "var(--color-card)",
    border: "1px solid var(--color-border)",
    borderRadius: 8,
    fontSize: 12,
  },
};

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
        <Tooltip {...TOOLTIP} />
        <Bar dataKey="value" fill="var(--color-primary)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AreaSeriesChart({ data, height = 220 }: { data: Point[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
        <CartesianGrid vertical={false} {...GRID} />
        <XAxis dataKey="label" tick={AXIS} interval="preserveStartEnd" />
        <YAxis tick={AXIS} width={40} />
        <Tooltip {...TOOLTIP} />
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
