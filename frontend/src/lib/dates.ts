/** Calendar day (UTC) from an ISO-ish timestamp, e.g. 2026-09-08. */
export function calendarDay(iso: string | null | undefined): string {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(String(iso ?? ""));
  return m?.[1] ?? "";
}

/** Human-readable date for operators (local timezone). */
export function formatHumanDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return calendarDay(iso) || String(iso).slice(0, 16);
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Short local datetime for version headers. */
export function formatHumanDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 19);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Monday (UTC) of the week containing `day` (YYYY-MM-DD). */
export function weekStartDay(day: string): string {
  const d = new Date(`${day}T00:00:00.000Z`);
  if (Number.isNaN(d.getTime())) return day;
  const dow = d.getUTCDay(); // 0 Sun … 6 Sat
  const offset = dow === 0 ? -6 : 1 - dow;
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0, 10);
}

export function formatWeekLabel(weekStart: string): string {
  return `Week of ${formatHumanDate(`${weekStart}T12:00:00.000Z`)}`;
}
