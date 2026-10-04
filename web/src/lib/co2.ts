import type { Co2, Period } from "./api";

export const COUNTS: Record<Period, number> = { day: 14, week: 12, month: 12 };
/** Keep sparse data from filling the card with oversized bars. */
const MIN_SLOTS = 7;

type Row = Co2["periods"][number];
/** Omit `p` for periods with no readings. */
export type Slot = { start: string; p?: Row };

export const fmtLb = (v: number) => (Math.abs(v) < 10 ? v.toFixed(2) : v.toFixed(1));

export function fmtWh(wh: number): [string, string] {
  if (Math.abs(wh) < 1000) return [String(Math.round(wh)), "Wh"];
  const k = wh / 1000;
  return [k.toFixed(Math.abs(k) < 10 ? 2 : Math.abs(k) < 100 ? 1 : 0), "kWh"];
}

const short = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const long = new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" });
const month = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });
const pacific = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" });

export function periodLabel(start: string, by: Period): string {
  if (by === "month") return month.format(new Date(`${start}-01T00:00:00Z`));
  return short.format(new Date(`${start}T00:00:00Z`));
}

export function periodName(start: string, by: Period): string {
  if (by === "month") return long.format(new Date(`${start}-01T00:00:00Z`));
  const d = periodLabel(start, by);
  return by === "week" ? `Week of ${d}` : d;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Return server-compatible Pacific period keys, oldest first, ending at `now`. */
export function periodKeys(by: Period, count: number, now: number): string[] {
  const today = new Date(`${pacific.format(new Date(now * 1000))}T00:00:00Z`);
  const keys: string[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(today);
    if (by === "day") d.setUTCDate(d.getUTCDate() - i);
    else if (by === "week") d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) - 7 * i);
    else {
      d.setUTCDate(1);
      d.setUTCMonth(d.getUTCMonth() - i);
    }
    keys.push(by === "month" ? iso(d).slice(0, 7) : iso(d));
  }
  return keys;
}

/** Keep missing periods on the axis so gaps remain visible. */
export function slots(periods: Row[], by: Period, now: number): Slot[] {
  const keys = periodKeys(by, COUNTS[by], now);
  const have = new Map(periods.map((p) => [p.start, p]));
  const first = keys.findIndex((k) => have.has(k));
  const from = Math.min(first < 0 ? keys.length : first, keys.length - MIN_SLOTS);
  return keys.slice(Math.max(0, from)).map((start) => ({ start, p: have.get(start) }));
}

/** Return rounded ticks spanning lo through hi in roughly `n` steps. */
export function niceTicks(lo: number, hi: number, n = 3): number[] {
  const raw = Math.max(hi - lo, 1e-9) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const a = Math.floor(lo / step + 1e-9);
  const b = Math.ceil(hi / step - 1e-9);
  return Array.from({ length: b - a + 1 }, (_, i) => +((a + i) * step).toPrecision(12));
}
