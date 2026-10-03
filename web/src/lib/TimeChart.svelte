<script lang="ts">
  // One uPlot chart on the shared clock. Plan windows and the PG&E peak are
  // painted behind the series and a line marks now. Hovering shows a tooltip
  // with the time and every series; the cursor is synced across charts.
  import uPlot from "uplot";
  import type { Window } from "./api";
  import { fmtClock, fmtDayClock, fmtWeekday, localMinutes, peakWindows } from "./time";

  export interface Series {
    label: string;
    color: string;
    fill?: string;
    dash?: number[];
    width?: number;
    unit: string;
    digits?: number;
  }

  let {
    data,
    series,
    from,
    to,
    now,
    windows = [],
    height = 160,
    yMax,
    yRule,
    label,
  }: {
    data: (number | null | undefined)[][];
    series: Series[];
    from: number;
    to: number;
    now: number;
    windows?: Window[];
    height?: number;
    yMax?: number;
    yRule?: { value: number; label: string };
    label: string;
  } = $props();

  let el: HTMLDivElement;
  let width = $state(600);
  let tip = $state<{ x: number; y: number; t: number; values: (number | null)[] } | null>(null);
  let hovering = false;

  const css = (name: string) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function bands(u: uPlot) {
    const { ctx } = u;
    const paint = (spans: [number, number][], color: string) => {
      ctx.fillStyle = color;
      for (const [s, e] of spans) {
        const x0 = u.valToPos(Math.max(s, from), "x", true);
        const x1 = u.valToPos(Math.min(e, to), "x", true);
        if (x1 > x0) ctx.fillRect(x0, u.bbox.top, x1 - x0, u.bbox.height);
      }
    };
    paint(peakWindows(from, to), css("--peak-band"));
    paint(windows, css("--plan-band"));
  }

  function overlays(u: uPlot) {
    const { ctx } = u;
    const dpr = devicePixelRatio;
    const x = Math.round(u.valToPos(now, "x", true));
    if (x >= u.bbox.left && x <= u.bbox.left + u.bbox.width) {
      ctx.strokeStyle = css("--ink-2");
      ctx.lineWidth = dpr;
      ctx.beginPath();
      ctx.moveTo(x, u.bbox.top);
      ctx.lineTo(x, u.bbox.top + u.bbox.height);
      ctx.stroke();
      ctx.fillStyle = css("--ink-2");
      ctx.font = `${11 * dpr}px ${css("--f-body")}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText("now", x + 4 * dpr, u.bbox.top + 2 * dpr);
    }
    if (yRule) {
      const y = Math.round(u.valToPos(yRule.value, "y", true));
      ctx.strokeStyle = css("--ink-3");
      ctx.lineWidth = dpr;
      ctx.setLineDash([4 * dpr, 3 * dpr]);
      ctx.beginPath();
      ctx.moveTo(u.bbox.left, y);
      ctx.lineTo(u.bbox.left + u.bbox.width, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = css("--ink-2");
      ctx.font = `${11 * dpr}px ${css("--f-body")}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      ctx.fillText(yRule.label, u.bbox.left + 6 * dpr, y - 3 * dpr);
    }
  }

  // Midnight ticks name the day, so a 48-hour axis reads "Sun" instead of "12 AM".
  const tickLabel = (t: number) => (localMinutes(t) === 0 ? fmtWeekday(t) : fmtClock(t));

  function setCursor(u: uPlot) {
    const i = u.cursor.idx;
    if (!hovering || i == null || u.cursor.left == null || u.cursor.left < 0) {
      tip = null;
      return;
    }
    const t = u.data[0][i];
    tip = {
      x: u.cursor.left + u.over.offsetLeft,
      y: (u.cursor.top ?? 0) + u.over.offsetTop,
      t,
      values: series.map((_, k) => {
        // Show the nearest real value, since series are sampled at different rates.
        const ys = u.data[k + 1];
        for (let d = 0; d < 30; d++) {
          for (const j of [i - d, i + d]) {
            const v = ys[j];
            if (v != null && Math.abs(u.data[0][j] - t) <= 600) return v;
          }
        }
        return null;
      }),
    };
  }

  function opts(w: number): uPlot.Options {
    const axis = {
      stroke: css("--ink-3"),
      grid: { stroke: css("--line"), width: 1 },
      ticks: { show: false },
      font: `11px ${css("--f-body")}`,
    };
    return {
      width: w,
      height,
      cursor: {
        sync: { key: "timeline" },
        y: false,
        points: { size: 8, width: 2, fill: css("--panel") },
      },
      legend: { show: false },
      scales: {
        x: { time: true, min: from, max: to },
        y: { range: [0, yMax ?? null] as uPlot.Range.MinMax },
      },
      axes: [
        { ...axis, space: 64, size: 28, values: (_u, ticks) => ticks.map(tickLabel) },
        { ...axis, size: 44 },
      ],
      series: [
        {},
        ...series.map((s) => ({
          label: s.label,
          stroke: css(s.color),
          fill: s.fill ? css(s.fill) : undefined,
          dash: s.dash,
          width: s.width ?? 2,
          spanGaps: false,
          points: { show: false },
        })),
      ],
      hooks: { drawClear: [bands], draw: [overlays], setCursor: [setCursor] },
    };
  }

  let plot: uPlot | undefined;
  $effect(() => {
    const d = data as unknown as uPlot.AlignedData;
    const w = width;
    plot?.destroy();
    plot = new uPlot(opts(w), d, el);
    const over = plot.over;
    over.addEventListener("mouseenter", () => (hovering = true));
    over.addEventListener("mouseleave", () => {
      hovering = false;
      tip = null;
    });
    return () => plot?.destroy();
  });

  const fmt = (v: number | null, s: Series) =>
    v == null ? "–" : `${v.toFixed(s.digits ?? 0)} ${s.unit}`;
</script>

<figure aria-label={label}>
  <ul class="legend">
    {#each series as s (s.label)}
      <li>
        <svg width="18" height="8" aria-hidden="true"
          ><line
            x1="1"
            x2="17"
            y1="4"
            y2="4"
            stroke="var({s.color})"
            stroke-width={s.width ?? 2}
            stroke-dasharray={s.dash?.join(" ")}
          /></svg
        >{s.label}
      </li>
    {/each}
  </ul>
  <div class="chart" bind:this={el} bind:clientWidth={width}>
    {#if tip}
      <div
        class="tip"
        class:left={tip.x > width - 200}
        style:left="{tip.x}px"
        style:top="{Math.min(tip.y, height - 90)}px"
      >
        <div class="when">{fmtDayClock(tip.t)}</div>
        {#each series as s, k (s.label)}
          {#if tip.values[k] != null}
          <div class="row">
            <span class="key" style:background="var({s.color})"></span>
            <strong>{fmt(tip.values[k], s)}</strong>
            <span class="name">{s.label}</span>
          </div>
          {/if}
        {/each}
      </div>
    {/if}
  </div>
</figure>

<style>
  figure {
    margin: 0;
    min-width: 0;
  }
  .legend {
    list-style: none;
    margin: 0 0 4px;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    font-size: 12px;
    color: var(--ink-2);
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .chart {
    position: relative;
    min-width: 0;
  }
  .tip {
    position: absolute;
    z-index: 2;
    pointer-events: none;
    transform: translate(12px, 0);
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.15);
    padding: 8px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  .tip.left {
    transform: translate(calc(-100% - 12px), 0);
  }
  .when {
    color: var(--ink-2);
    margin-bottom: 4px;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 6px;
    line-height: 1.6;
  }
  .row strong {
    color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .name {
    color: var(--ink-3);
  }
  .key {
    width: 10px;
    height: 2px;
    border-radius: 1px;
  }
</style>
