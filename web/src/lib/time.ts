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

export const fmtClock = (t: number) => clock.format(t * 1000).replace(":00", "");
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

export function ago(seconds: number): string {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}
