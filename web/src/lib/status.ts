import type { PlugReport, Window } from "./api";
import { fmtDayClock, peakWindows } from "./time";

const REASONS: Record<string, string> = {
  peak: "PG&E peak (4–9 pm), so the grid stays off",
  safety: "Safety charge after a long time off the grid",
  index: "Following WattTime's live index because the plan is out of date",
  fallback: "No plan or live index, so using the 10 am–3 pm fallback",
  "no-time": "The plug doesn't know the time yet",
  start: "The plug just started",
};

export function explain(plug: PlugReport, windows: Window[], now: number): string {
  if (plug.reason === "plan") {
    const w = windows.find(([s, e]) => s <= now && now < e);
    if (plug.on && w) return `Clean window until ${fmtDayClock(w[1])}`;
    return plug.on ? "Clean window" : "Waiting for the next clean window";
  }
  return REASONS[plug.reason] ?? plug.reason;
}

export interface Change {
  t: number;
  label: string;
  peak?: boolean;
}

/** The next few times the plan or the peak flips the grid. */
export function upcoming(windows: Window[], now: number, n = 3): Change[] {
  const out: Change[] = [];
  for (const [s, e] of windows) {
    if (s > now) out.push({ t: s, label: `${fmtDayClock(s)} on` });
    if (e > now) out.push({ t: e, label: `${fmtDayClock(e)} off` });
  }
  for (const [s, e] of peakWindows(now, now + 36 * 3600)) {
    if (e > now)
      out.push({
        t: Math.max(s, now),
        label:
          s > now
            ? `${fmtDayClock(s)}–${fmtDayClock(e).split(" ").slice(1).join(" ")} peak`
            : `Peak until ${fmtDayClock(e)}`,
        peak: true,
      });
  }
  return out.sort((a, b) => a.t - b.t).slice(0, n);
}
