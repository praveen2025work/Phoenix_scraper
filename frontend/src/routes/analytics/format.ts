export const num = (v: unknown, digits = 0): string =>
  v == null || v === "" ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });

export const pct = (v: unknown): string =>
  v == null || v === "" ? "—" : `${Math.round(Number(v) * 100)}%`;

export const usd = (v: unknown): string =>
  v == null || v === "" ? "—" : `$${Number(v).toFixed(2)}`;

export const truncate = (v: unknown, n = 70): string => {
  const s = String(v ?? "");
  return s.length > n ? `${s.slice(0, n)}…` : s;
};

export const modelShort = (v: unknown): string => {
  const s = String(v ?? "");
  return s.includes(".") ? s.split(".").pop()! : s;
};
