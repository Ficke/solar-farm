import type { PlugReport } from "./api";
import { MODES, type Mode } from "./plan";

const REASONS: Record<string, string> = {
  peak: "Peak hours, 4–9 PM",
  "peak-low": "Peak, battery ≤ 10%",
  safety: "Safety charge",
  index: "Following live CO₂ index",
  fallback: "Offline schedule, 10 AM–3 PM",
  "no-time": "Plug clock not set",
  start: "Plug starting",
};

/** Name the plan mode behind a plan-driven relay state when it agrees with the relay. */
export function explain(plug: PlugReport, mode?: Mode): string {
  if (plug.reason === "plan") {
    if (mode && MODES[mode].on === plug.on) return MODES[mode].label;
    return plug.on ? "Planned window" : "Outside planned windows";
  }
  return REASONS[plug.reason] ?? plug.reason;
}
