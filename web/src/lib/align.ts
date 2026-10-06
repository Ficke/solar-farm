type Points = [number, number | null | undefined][];

/**
 * Align [Unix seconds, value] series on one sorted uPlot axis.
 * Use undefined to connect missing timestamps and null to break the line
 * across outages longer than the series' gap, defaulting to 15 minutes.
 */
export function align(series: Points[], gaps: number[] = []): (number | null | undefined)[][] {
  const xs = [...new Set(series.flatMap((s) => s.map((p) => p[0])))].sort((a, b) => a - b);
  const index = new Map(xs.map((x, i) => [x, i]));
  const out: (number | null | undefined)[][] = [xs, ...series.map(() => xs.map(() => undefined))];
  series.forEach((s, k) => {
    const ys = out[k + 1];
    const gap = gaps[k] ?? 15 * 60;
    let prev: number | undefined;
    for (const [t, v] of s) {
      if (v == null) continue;
      const i = index.get(t) as number;
      if (prev !== undefined && t - prev > gap && i > 0 && ys[i - 1] === undefined)
        ys[i - 1] = null;
      ys[i] = v;
      prev = t;
    }
  });
  return out;
}

const STEPS = [120, 300, 600, 900, 1800, 3600];

/** Choose an averaging step for roughly `px` pixels per point; zero keeps raw data. */
export function stepFor(span: number, width: number, px = 3): number {
  const want = (span / Math.max(1, width)) * px;
  return want <= 60 ? 0 : (STEPS.find((s) => s >= want) ?? 3600);
}

/**
 * Average aligned values in `step`-second buckets at their mean timestamp.
 * Preserve null gaps and undefined timestamps when a bucket has no values.
 */
export function bucket(
  data: (number | null | undefined)[][],
  step: number,
): (number | null | undefined)[][] {
  const xs = data[0] as number[];
  if (!step || xs.length < 2) return data;
  const out: (number | null | undefined)[][] = data.map(() => []);
  let i = 0;
  while (i < xs.length) {
    const key = Math.floor(xs[i] / step);
    let j = i;
    let tsum = 0;
    while (j < xs.length && Math.floor(xs[j] / step) === key) tsum += xs[j++];
    out[0].push(tsum / (j - i));
    for (let k = 1; k < data.length; k++) {
      let sum = 0;
      let n = 0;
      let gap = false;
      for (let m = i; m < j; m++) {
        const v = data[k][m];
        if (v == null) gap ||= v === null;
        else {
          sum += v;
          n++;
        }
      }
      // A gap that ends inside this bucket still breaks the line before it.
      if (gap && n && out[k].at(-1) === undefined && out[k].length)
        out[k][out[k].length - 1] = null;
      out[k].push(n ? sum / n : gap ? null : undefined);
    }
    i = j;
  }
  return out;
}

/** Readings further than this from a time, in seconds, don't describe it. */
export const NEAR = 600;

/** Return the item closest to `t` within `NEAR` seconds. */
export function nearest<T>(items: T[], t: number, at: (item: T) => number): T | null {
  let best: T | null = null;
  let gap = NEAR;
  for (const item of items) {
    const d = Math.abs(at(item) - t);
    if (d <= gap) {
      best = item;
      gap = d;
    }
  }
  return best;
}
