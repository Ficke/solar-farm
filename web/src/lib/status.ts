import type { PlugReport } from "./api";

const REASONS: Record<string, string> = {
  peak: "Peak hours, 4–9 PM",
  safety: "Safety charge",
  index: "Following live CO₂ index",
  fallback: "Offline schedule, 10 AM–3 PM",
  "no-time": "Plug clock not set",
  start: "Plug starting",
};

/** Why the plug is in its current state, in a few words. */
export function explain(plug: PlugReport): string {
  if (plug.reason === "plan") return plug.on ? "Planned window" : "Outside planned windows";
  return REASONS[plug.reason] ?? plug.reason;
}
