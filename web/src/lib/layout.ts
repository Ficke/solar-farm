// Share chart gutters with the plan strip to align time axes.
export const AXIS_W = 48;
export const PAD_R = 12;
export const PAST = 24 * 3600;
export const FUTURE = 24 * 3600;

import { localMinutes } from "./time";

/** Space Pacific ticks 3, 6 or 12 hours apart according to width. */
export function hourTicks(from: number, to: number, width: number): number[] {
  const step = width < 450 ? 720 : width < 700 ? 360 : 180;
  const out: number[] = [];
  for (let t = from - (from % 3600) + 3600; t <= to; t += 3600) {
    if (localMinutes(t) % step === 0) out.push(t);
  }
  return out;
}

/** Choose Pacific ticks on five-minute boundaries, targeting `gap` pixels. */
export function timeTicks(from: number, to: number, width: number, gap = 72): number[] {
  const steps = [5, 10, 15, 30, 60, 120, 180, 360, 720];
  const fit = (to - from) / 60 / Math.max(1, width / gap);
  const step = steps.find((s) => s >= fit) ?? 1440;
  const out: number[] = [];
  for (let t = from - (from % 300) + 300; t <= to; t += 300) {
    if (localMinutes(t) % step === 0) out.push(t);
  }
  return out;
}

/** Limit zoom to at least 15 minutes. */
export const MIN_SPAN = 15 * 60;

/** Share CSS-pixel widths for primary and secondary chart lines. */
export const LINE = 1.5;
export const LINE_THIN = 1;
