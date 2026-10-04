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
