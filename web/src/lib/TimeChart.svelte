<script lang="ts">
  // One uPlot chart on the shared 48-hour clock. Plan windows and the PG&E
  // peak are painted as bands behind the series; a line marks now.
  import uPlot from "uplot";
  import type { Window } from "./api";
  import { fmtClock, fmtDayClock, peakWindows } from "./time";

  interface Series {
    label: string;
    color: string;
    fill?: string;
    dash?: number[];
    unit: string;
  }

  let {
    data,
    series,
    from,
    to,
    now,
    windows,
    height = 160,
    yMax,
    yRule,
  }: {
    data: (number | null | undefined)[][];
    series: Series[];
    from: number;
    to: number;
    now: number;
    windows: Window[];
    height?: number;
    yMax?: number;
    yRule?: { value: number; label: string };
  } = $props();

  let el: HTMLDivElement;
  let width = $state(600);

  const css = (name: string) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function bands(u: uPlot) {
    const { ctx } = u;
    const top = u.bbox.top;
    const h = u.bbox.height;
    const paint = (spans: [number, number][], color: string) => {
      ctx.fillStyle = color;
      for (const [s, e] of spans) {
        const x0 = u.valToPos(Math.max(s, from), "x", true);
        const x1 = u.valToPos(Math.min(e, to), "x", true);
        if (x1 > x0) ctx.fillRect(x0, top, x1 - x0, h);
      }
    };
    paint(peakWindows(from, to), css("--peak-band"));
    paint(windows, css("--plan-band"));
  }

  function overlays(u: uPlot) {
    const { ctx } = u;
    const x = Math.round(u.valToPos(now, "x", true));
    ctx.strokeStyle = css("--ink");
    ctx.lineWidth = 1.2 * devicePixelRatio;
    ctx.beginPath();
    ctx.moveTo(x, u.bbox.top);
    ctx.lineTo(x, u.bbox.top + u.bbox.height);
    ctx.stroke();
    if (yRule) {
      const y = Math.round(u.valToPos(yRule.value, "y", true));
      ctx.strokeStyle = css("--accent");
      ctx.setLineDash([4 * devicePixelRatio, 3 * devicePixelRatio]);
      ctx.beginPath();
      ctx.moveTo(u.bbox.left, y);
      ctx.lineTo(u.bbox.left + u.bbox.width, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = css("--accent");
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      ctx.font = `${11 * devicePixelRatio}px ${css("--f-mono")}`;
      ctx.fillText(yRule.label, u.bbox.left + 6 * devicePixelRatio, y - 4 * devicePixelRatio);
    }
  }

  function opts(w: number): uPlot.Options {
    const ink3 = css("--ink-3");
    const line = css("--line");
    const axis = {
      stroke: ink3,
      grid: { stroke: line, width: 1 },
      ticks: { show: false },
      font: `11px ${css("--f-mono")}`,
    };
    return {
      width: w,
      height,
      cursor: { sync: { key: "timeline" }, points: { size: 7 } },
      legend: { show: true, live: true },
      scales: {
        x: { time: true, min: from, max: to },
        y: { range: [0, yMax ?? null] as uPlot.Range.MinMax },
      },
      axes: [
        { ...axis, space: 70, size: 30, values: (_u, ticks) => ticks.map((t) => fmtClock(t)) },
        { ...axis, size: 44 },
      ],
      series: [
        { label: "", value: (_u, v) => (v == null ? "" : fmtDayClock(v)) },
        ...series.map((s) => ({
          label: s.label,
          stroke: css(s.color),
          fill: s.fill ? css(s.fill) : undefined,
          dash: s.dash,
          width: 2,
          spanGaps: false,
          points: { show: false },
          value: (_u: uPlot, v: number | null) => (v == null ? "–" : `${Math.round(v)} ${s.unit}`),
        })),
      ],
      hooks: { drawClear: [bands], draw: [overlays] },
    };
  }

  let plot: uPlot | undefined;
  $effect(() => {
    // Rebuild when the data, the window or the size changes.
    const d = data as unknown as uPlot.AlignedData;
    const w = width;
    plot?.destroy();
    plot = new uPlot(opts(w), d, el);
    return () => plot?.destroy();
  });
</script>

<div class="chart" bind:this={el} bind:clientWidth={width}></div>

<style>
  .chart {
    min-width: 0;
  }
  .chart :global(.u-legend) {
    text-align: left;
    font-size: 12px;
    color: var(--ink-2);
  }
  .chart :global(.u-legend .u-series:first-child) {
    display: none;
  }
  .chart :global(.u-legend .u-marker) {
    border-radius: 2px;
  }
</style>
