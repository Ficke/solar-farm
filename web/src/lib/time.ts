// Everything is shown on Pacific time, the clock PG&E's peak runs on.
export const TZ = "America/Los_Angeles";
export const PEAK = { start: 16, end: 21 }; // E-TOU-C, every day

const clock = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  hour: "numeric",
  minute: "2-digit",
});
const dayClock = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});
const parts = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  hour: "numeric",
  minute: "numeric",
  hourCycle: "h23",
});

const weekday = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short" });
const dayKey = new Intl.DateTimeFormat("en-CA", { timeZone: TZ });

export const fmtClock = (t: number) => clock.format(t * 1000).replace(":00", "");
export const fmtWeekday = (t: number) => weekday.format(t * 1000);
/** Clock time with the weekday only when it isn't today. */
export const fmtWhen = (t: number, now: number) =>
  dayKey.format(t * 1000) === dayKey.format(now * 1000)
    ? fmtClock(t)
    : `${fmtWeekday(t)} ${fmtClock(t)}`;
/** "3–4 PM", "11 AM–1 PM", "3:30–4 PM". */
export function fmtRange(s: number, e: number): string {
  const a = fmtClock(s);
  const b = fmtClock(e);
  const [am, bm] = [a.slice(-2), b.slice(-2)];
  return am === bm ? `${a.slice(0, -3)}–${b}` : `${a}–${b}`;
}
export const fmtDayClock = (t: number) => dayClock.format(t * 1000).replace(":00", "");

/** Minutes after local midnight in Pacific time. */
export function localMinutes(t: number): number {
  const p = parts.formatToParts(t * 1000);
  const h = Number(p.find((x) => x.type === "hour")?.value ?? 0);
  const m = Number(p.find((x) => x.type === "minute")?.value ?? 0);
  return h * 60 + m;
}

/** Peak windows (unix seconds) that overlap [from, to]. */
export function peakWindows(from: number, to: number): [number, number][] {
  const out: [number, number][] = [];
  // Walk local midnights by stepping from `from` back to its local midnight.
  let midnight = from - localMinutes(from) * 60 - (from % 60);
  midnight -= 86400;
  while (midnight < to + 86400) {
    // DST days are off by an hour at most; recompute from the real offset.
    const start = midnight + PEAK.start * 3600;
    const fix = (localMinutes(start) - PEAK.start * 60) * 60;
    const s = start - fix;
    const e = s + (PEAK.end - PEAK.start) * 3600;
    if (e > from && s < to) out.push([s, e]);
    midnight += 86400;
  }
  return out;
}

export function hours(seconds: number): string {
  const h = seconds / 3600;
  return h === 1 ? "1 hour" : `${Number.isInteger(h) ? h : h.toFixed(1)} hours`;
}

export function ago(seconds: number): string {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}
