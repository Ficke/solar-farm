import type { Now, PlugReport, Sample, Window } from "./api";

export type PlanBlock = NonNullable<Now["plan"]>["blocks"][number];
export type Mode = PlanBlock["mode"];

/** Grid to battery to outlet loses about 19% at 90% efficiency each way. */
export const ROUND_TRIP = 0.81;

export const MODES: Record<Mode, { label: string; rule: string; on: boolean }> = {
  charge: {
    label: "Charging from grid",
    rule: "Plug on. Charges in the cleanest grid hours so the battery is full by 4 PM.",
    on: true,
  },
  bypass: {
    label: "Running on grid",
    rule: `Plug on, battery full. Devices run on grid power now because it is cleaner than recharging later, after ${Math.round((1 - ROUND_TRIP) * 100)}% charging losses.`,
    on: true,
  },
  // Room for solar caps how much the plan charges, not when, so the strip
  // draws it as plug off and only the tooltip names it.
  solar: { label: "Running on battery", rule: "", on: false },
  battery: {
    label: "Running on battery",
    rule: "Plug off. Devices run on the battery and solar.",
    on: false,
  },
  peak: {
    label: "Peak, 4–9 PM",
    rule: "PG&E peak rate. Plug off unless the battery drops to 10%.",
    on: false,
  },
  none: { label: "No forecast", rule: "", on: false },
};
export const KEY: Mode[] = ["charge", "bypass", "battery", "peak"];

export interface Segment {
  s: number;
  e: number;
  mode: Mode;
  moer: number | null;
}

/** Merge adjacent blocks that share a mode; average emissions by duration. */
export function segments(blocks: PlanBlock[]): Segment[] {
  const out: (Segment & { w: number; sum: number })[] = [];
  for (const b of blocks) {
    const last = out.at(-1);
    const d = b.e - b.s;
    if (last && last.mode === b.mode && last.e === b.s) {
      last.e = b.e;
      if (b.moer != null) {
        last.sum += b.moer * d;
        last.w += d;
      }
    } else {
      out.push({ ...b, w: b.moer != null ? d : 0, sum: (b.moer ?? 0) * d });
    }
  }
  return out.map(({ s, e, mode, w, sum }) => ({ s, e, mode, moer: w ? sum / w : null }));
}

/** Plans saved before per-block output only carry charging windows. */
export const fromWindows = (windows: Window[]): Segment[] =>
  windows.map(([s, e]) => ({ s, e, mode: "charge", moer: null }));

export const blockAt = (blocks: PlanBlock[], t: number) =>
  blocks.find((b) => t >= b.s && t < b.e) ?? null;

/** A plug report covers the minute after it; longer silences show no state. */
export const REPORT_GAP = 180;
/** With the plug on, a battery at or above this that stops rising is passing grid power to loads. */
export const FULL_PCT = 99;
const RISE_WINDOW = 900;

/** Rebuild past plug states from plug reports and battery readings. */
export function actual(plug: PlugReport[], samples: Sample[], until: number): Segment[] {
  const pct = samples.filter((p) => p.battery_pct != null);
  let j = 0;
  const out: Segment[] = [];
  plug.forEach((r, i) => {
    const e = Math.min(plug[i + 1]?.t ?? until, r.t + REPORT_GAP, until);
    if (e <= r.t) return;
    while (j + 1 < pct.length && pct[j + 1].t <= r.t) j++;
    const p = pct[j] && Math.abs(pct[j].t - r.t) <= 600 ? pct[j].battery_pct : null;
    if (r.on && p == null) return;
    const rising = () => {
      for (let k = j + 1; k < pct.length && pct[k].t <= r.t + RISE_WINDOW; k++) {
        if ((pct[k].battery_pct as number) > (p as number)) return true;
      }
      return false;
    };
    const mode: Mode = !r.on
      ? "battery"
      : (p as number) < FULL_PCT || rising()
        ? "charge"
        : "bypass";
    const last = out.at(-1);
    if (last && last.mode === mode && last.e === r.t) last.e = e;
    else out.push({ s: r.t, e, mode, moer: null });
  });
  return out;
}

/** Grid use that happened, then the planned windows from now on. */
export const gridSpans = (
  plug: PlugReport[],
  samples: Sample[],
  windows: Window[],
  now: number,
): Window[] => [
  ...actual(plug, samples, now)
    .filter((g) => MODES[g.mode].on)
    .map((g): Window => [g.s, g.e]),
  ...windows.filter(([, e]) => e > now).map(([s, e]): Window => [Math.max(s, now), e]),
];
