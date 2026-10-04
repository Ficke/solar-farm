import type { Period } from "./api";

export const COUNTS: Record<Period, number> = { day: 14, week: 12, month: 12 };

/** Pounds with two decimals under 10, one above. */
export const fmtLb = (v: number) => (Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1));

const short = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const long = new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" });
const month = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });

/** "Oct 4" for a day or the week starting then, "Oct" for a month. */
export function periodLabel(start: string, by: Period): string {
  if (by === "month") return month.format(new Date(`${start}-01T00:00:00Z`));
  return short.format(new Date(`${start}T00:00:00Z`));
}

/** The heading for one period: "Oct 4", "Week of Sep 28", "October". */
export function periodName(start: string, by: Period): string {
  if (by === "month") return long.format(new Date(`${start}-01T00:00:00Z`));
  const d = periodLabel(start, by);
  return by === "week" ? `Week of ${d}` : d;
}
