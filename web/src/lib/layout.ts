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

/**
 * Ticks for any span, on whole local quarter hours or hours, at least
 * `gap` px apart. Used once a chart is zoomed in.
 */
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

/** The narrowest span a chart zooms to, in seconds. */
export const MIN_SPAN = 15 * 60;

/** Line weights, in CSS px, for every chart: data lines, then secondary ones (forecasts, load, rules). */
export const LINE = 1.5;
export const LINE_THIN = 1;
