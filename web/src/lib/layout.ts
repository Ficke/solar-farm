// Every time chart and the plan strip share this geometry, so their time
// axes line up: AXIS_W for the y-axis on the left, PAD_R on the right.
export const AXIS_W = 48;
export const PAD_R = 12;
export const PAST = 24 * 3600;
export const FUTURE = 24 * 3600;

import { localMinutes } from "./time";

/** Ticks on whole local hours, every 3 hours on wide screens and 6 on narrow. */
export function hourTicks(from: number, to: number, width: number): number[] {
  const step = width < 450 ? 720 : width < 700 ? 360 : 180;
  const out: number[] = [];
  for (let t = from - (from % 3600) + 3600; t <= to; t += 3600) {
    if (localMinutes(t) % step === 0) out.push(t);
  }
  return out;
}
