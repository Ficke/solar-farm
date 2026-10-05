import type { Now, Window } from "./api";

export type PlanBlock = NonNullable<Now["plan"]>["blocks"][number];
export type Mode = PlanBlock["mode"];

/** Grid to battery to outlet loses about 19% at 90% efficiency each way. */
export const ROUND_TRIP = 0.81;

export const MODES: Record<Mode, { label: string; rule: string; on: boolean }> = {
  charge: { label: "Charge", rule: "Cleanest blocks, full by 4 PM", on: true },
  bypass: { label: "Grid to loads", rule: `CO₂ ≤ recharge ÷ ${ROUND_TRIP}`, on: true },
  // Room for solar caps how much the plan charges, not when, so the strip
  // draws it as plug off and only the tooltip names it.
  solar: { label: "Battery, solar room", rule: "", on: false },
  battery: { label: "Battery", rule: "Plug off", on: false },
  peak: { label: "Peak", rule: "4–9 PM, plug off", on: false },
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
