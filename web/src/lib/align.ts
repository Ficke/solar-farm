type Points = [number, number | null | undefined][];

/**
 * Merge several [t, v] series onto one sorted x axis for uPlot. Where a
 * series simply has no point at another series' time the value is
 * `undefined`, which uPlot draws through; after a break longer than that
 * series' gap (15 minutes unless given) it is `null`, drawn as a gap.
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

/** The averaging step that leaves about `px` pixels per point, or 0 for none. */
export function stepFor(span: number, width: number, px = 3): number {
  const want = (span / Math.max(1, width)) * px;
  return want <= 60 ? 0 : (STEPS.find((s) => s >= want) ?? 3600);
}

/**
 * Average aligned series into `step`-second buckets, so a dense series
 * draws as a readable line rather than a band of noise. Each bucket sits at
 * the mean time of its points. A bucket with no values keeps a gap (null)
 * if it had one, and is otherwise left out of that series (undefined).
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
