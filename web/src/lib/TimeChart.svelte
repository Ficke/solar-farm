<script lang="ts">
  // One uPlot chart on the shared clock. Plan windows and the PG&E peak are
  // painted behind the series and a line marks now. Hovering shows a tooltip
  // with the time and every series; the cursor is synced across charts.
  //
  // The plot is built once and updated in place: new data, a new time range
  // or a new size never recreate it, so hovering survives a refresh. Only a
  // change of series, height or theme rebuilds it.
  import { untrack } from "svelte";
  import uPlot from "uplot";
  import type { Window } from "./api";
  import { hover } from "./hover.svelte";
  import { AXIS_W, hourTicks, PAD_R } from "./layout";
  import Tooltip, { type TipRow } from "./Tooltip.svelte";
  import { theme } from "./theme.svelte";
  import { fmtClock, fmtDayClock, fmtWeekday, localMinutes, peakWindows } from "./time";

  export interface Series {
    label: string;
    color: string;
    fill?: string;
    /** Solid area: a square key instead of a line. */
    area?: boolean;
    dash?: number[];
    /** Color the line by its value: [value, color token] stops, low to high. */
    ramp?: [number, string][];
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
    tipData,
    shade = true,
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
    /** Values for the tooltip when the drawn ones differ, e.g. a stacked chart. */
    tipData?: (number | null | undefined)[][];
    /** Paint the peak and plan bands behind the series. */
    shade?: boolean;
  } = $props();

  let el: HTMLDivElement;
  let width = $state(600);
  let tip = $state<{ x: number; y: number; t: number; values: (number | null)[] } | null>(null);
  let hovering = false;

  const css = (name: string) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // Diagonal hatching for the peak, so it reads apart from plan windows
  // without relying on hue.
  function hatch(ctx: CanvasRenderingContext2D, color: string) {
    const n = Math.round(6 * devicePixelRatio);
    const tile = document.createElement("canvas");
    tile.width = tile.height = n;
    const t = tile.getContext("2d");
    if (!t) return color;
    t.strokeStyle = color;
    t.lineWidth = devicePixelRatio;
    t.beginPath();
    t.moveTo(-1, n + 1);
    t.lineTo(n + 1, -1);
    t.stroke();
    return ctx.createPattern(tile, "repeat") ?? color;
  }

  function bands(u: uPlot) {
    if (!shade) return;
    const { ctx } = u;
    // uPlot caches the canvas styles it last set, so hooks restore theirs.
    ctx.save();
    const paint = (spans: [number, number][], color: string | CanvasPattern) => {
      ctx.fillStyle = color;
      for (const [s, e] of spans) {
        const x0 = u.valToPos(Math.max(s, from), "x", true);
        const x1 = u.valToPos(Math.min(e, to), "x", true);
        if (x1 > x0) ctx.fillRect(x0, u.bbox.top, x1 - x0, u.bbox.height);
      }
    };
    paint(peakWindows(from, to), hatch(ctx, css("--peak-hatch")));
    paint(windows, css("--plan-band"));
    ctx.restore();
  }

  function overlays(u: uPlot) {
    const { ctx } = u;
    ctx.save();
    const dpr = devicePixelRatio;
    const x = Math.round(u.valToPos(now, "x", true));
    if (x >= u.bbox.left && x <= u.bbox.left + u.bbox.width) {
      ctx.strokeStyle = css("--ink-3");
      ctx.lineWidth = dpr;
      ctx.beginPath();
      ctx.moveTo(x, u.bbox.top);
      ctx.lineTo(x, u.bbox.top + u.bbox.height);
      ctx.stroke();
      ctx.fillStyle = css("--ink-2");
      ctx.font = `500 ${11 * dpr}px ${css("--f-sans")}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText("Now", x + 4 * dpr, u.bbox.top + 2 * dpr);
    }
    if (yRule) {
      const y = Math.round(u.valToPos(yRule.value, "y", true));
      ctx.strokeStyle = css("--ink-3");
      ctx.lineWidth = dpr;
      ctx.setLineDash([2 * dpr, 3 * dpr]);
      ctx.beginPath();
      ctx.moveTo(u.bbox.left, y);
      ctx.lineTo(u.bbox.left + u.bbox.width, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = css("--ink-2");
      ctx.font = `${11 * dpr}px ${css("--f-sans")}`;
      ctx.textAlign = "left";
      // At the right end, over the future where no readings are drawn, and
      // below the rule when there's no room above it.
      const below = y - u.bbox.top < 16 * dpr;
      ctx.textAlign = "right";
      ctx.textBaseline = below ? "top" : "bottom";
      ctx.fillText(
        yRule.label,
        u.bbox.left + u.bbox.width - 6 * dpr,
        below ? y + 3 * dpr : y - 3 * dpr,
      );
    }
    ctx.restore();
  }

  // Midnight ticks name the day, so a 48-hour axis reads "Sun" instead of "12 AM".
  const tickLabel = (t: number) => (localMinutes(t) === 0 ? fmtWeekday(t) : fmtClock(t));

  function setCursor(u: uPlot) {
    const i = u.cursor.idx;
    if (!hovering || i == null || u.cursor.left == null || u.cursor.left < 0) {
      tip = null;
      return;
    }
    hover.t = u.posToVal(u.cursor.left, "x");
    hover.from = "chart";
    const t = u.data[0][i];
    tip = {
      x: u.cursor.left + u.over.offsetLeft,
      y: (u.cursor.top ?? 0) + u.over.offsetTop,
      t,
      values: series.map((_, k) => {
        // Show the nearest real value, since series are sampled at different rates.
        const ys = (tipData ?? u.data)[k + 1];
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

  // A vertical gradient whose stops sit at the ramp's values on the y scale.
  function rampStroke(ramp: [number, string][]) {
    return (u: uPlot) => {
      const lo = ramp[0][0];
      const hi = ramp[ramp.length - 1][0];
      const y0 = u.valToPos(lo, "y", true);
      const y1 = u.valToPos(hi, "y", true);
      if (!Number.isFinite(y0) || !Number.isFinite(y1) || y0 === y1) return css(ramp[0][1]);
      const g = u.ctx.createLinearGradient(0, y0, 0, y1);
      for (const [v, c] of ramp) g.addColorStop((v - lo) / (hi - lo), css(c));
      return g;
    };
  }

  function opts(w: number): uPlot.Options {
    const axis = {
      stroke: css("--ink-3"),
      grid: { stroke: css("--rule"), width: 1 },
      ticks: { show: false },
      font: `11px ${css("--f-sans")}`,
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
      padding: [6, PAD_R, 0, 0],
      scales: {
        x: { time: true, range: () => [from, to] },
        // A fixed floor and a fallback ceiling keep the y-axis, and with it
        // the time axis, in place when a chart has no data yet.
        y: {
          range: (_u, _min, max) =>
            yMax != null ? [0, yMax] : uPlot.rangeNum(0, max ?? 1, 0.1, true),
        },
      },
      axes: [
        {
          ...axis,
          grid: { show: false },
          size: 28,
          splits: (u) => hourTicks(from, to, u.width),
          values: (_u, ticks) => ticks.map(tickLabel),
        },
        { ...axis, size: AXIS_W },
      ],
      series: [
        {},
        ...series.map((s) => ({
          label: s.label,
          // Stacked areas get a surface-colored edge so adjacent fills separate.
          stroke: s.ramp ? rampStroke(s.ramp) : s.area ? css("--bg") : css(s.color),
          fill: s.fill ? css(s.fill) : undefined,
          dash: s.dash,
          width: s.width ?? (s.area ? 1 : 2),
          spanGaps: false,
          points: { show: false },
        })),
      ],
      hooks: { drawClear: [bands], draw: [overlays], setCursor: [setCursor] },
    };
  }

  let plot: uPlot | undefined;
  // Everything that shapes the plot itself; when this changes it is rebuilt.
  const shape = $derived(JSON.stringify([series, height, yMax, theme.version]));

  $effect(() => {
    shape;
    const u = untrack(() => new uPlot(opts(width), data as unknown as uPlot.AlignedData, el));
    u.over.addEventListener("mouseenter", () => (hovering = true));
    u.over.addEventListener("mouseleave", () => {
      hovering = false;
      tip = null;
      hover.t = null;
    });
    plot = u;
    return () => {
      u.destroy();
      plot = undefined;
    };
  });

  // New readings or a moved time axis: same plot, new data and scales.
  $effect(() => {
    const d = data as unknown as uPlot.AlignedData;
    from;
    to;
    untrack(() => plot?.setData(d));
  });

  $effect(() => {
    const w = width;
    untrack(() => plot && plot.width !== w && plot.setSize({ width: w, height }));
  });

  // The now line, bands and target rule are drawn in hooks; repaint when they move.
  $effect(() => {
    now;
    windows;
    yRule;
    shade;
    untrack(() => plot?.redraw(false));
  });

  // Follow the pointer on the plan strip; charts already sync with each other.
  $effect(() => {
    const { t, from: source } = hover;
    if (!plot || source !== "plan") return;
    plot.setCursor(
      t == null
        ? { left: -10, top: -10 }
        : { left: plot.valToPos(t, "x"), top: plot.over.clientHeight / 2 },
    );
  });

  const tipRows = (values: (number | null)[]): TipRow[] =>
    series.flatMap((s, k) => {
      const v = values[k];
      if (v == null) return [];
      const value = `${v.toFixed(s.digits ?? 0)} ${s.unit}`;
      return [{ color: s.color, shape: s.area ? "square" : "line", value, name: s.label }];
    });
</script>

<figure aria-label={label}>
  <ul class="legend">
    {#each series as s (s.label)}
      <li>
        {#if s.area}
          <span class="swatch" style:background="var({s.color})"></span>
        {:else if s.ramp}
          <span
            class="ramp"
            class:dash={s.dash}
            style:background="linear-gradient(90deg, {s.ramp.map(([, c]) => `var(${c})`).join(', ')})"
          ></span>
        {:else}
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
        >
        {/if}{s.label}
      </li>
    {/each}
  </ul>
  <div class="chart" bind:this={el} bind:clientWidth={width}>
    {#if tip}
      {@const t = tip}
      <Tooltip
        x={t.x}
        y={Math.min(t.y, height - 90)}
        flip={t.x > width - 200}
        title={fmtDayClock(t.t)}
        rows={tipRows(t.values)}
      />
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
    margin: 0 0 6px;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px 16px;
    font-size: 12px;
    color: var(--ink-2);
  }
  .ramp {
    width: 18px;
    height: 2px;
    border-radius: 1px;
  }
  .ramp.dash {
    mask: repeating-linear-gradient(90deg, #000 0 4px, transparent 4px 7px);
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
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
</style>
