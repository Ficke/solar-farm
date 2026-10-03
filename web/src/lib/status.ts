import type { PlugReport, Window } from "./api";
import { fmtWhen } from "./time";

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
    if (plug.on && w) return `Planned clean window, until ${fmtWhen(w[1], now)}`;
    return plug.on ? "Planned clean window" : "Outside the planned clean windows";
  }
  return REASONS[plug.reason] ?? plug.reason;
}
