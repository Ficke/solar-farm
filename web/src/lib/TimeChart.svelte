<script lang="ts">
  // One uPlot chart on the shared clock. Plan windows and the PG&E peak are
  // painted behind the series and a line marks now. Hovering shows a tooltip
  // with the time and every series; the cursor is synced across charts.
  //
  // The plot is built once and updated in place: new data, a new time range
  // or a new size never recreate it, so hovering survives a refresh. Only a
  // change of series or theme rebuilds it.
  //
  // With a `title` the chart gets an expand button that opens it full screen
  // (ChartDialog), where `mode` is "expanded": dragging across it with a mouse
  // zooms to that span (`view`, reported through `onview`), and a double click
  // zooms back out. "overview" is the small whole-range chart under it.
  import { untrack } from "svelte";
  import uPlot from "uplot";
  import { bucket, stepFor } from "./align";
  import type { Window } from "./api";
  import ChartDialog from "./ChartDialog.svelte";
  import { hover } from "./hover.svelte";
  import { AXIS_W, hourTicks, LINE, LINE_THIN, MIN_SPAN, PAD_R, timeTicks } from "./layout";
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
    title,
    mode = "inline",
    view,
    onview,
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
    /** Heading in full screen; charts without one have no expand button. */
    title?: string;
    mode?: "inline" | "expanded" | "overview";
    /** The visible time span when zoomed in; [from, to] otherwise. */
    view?: [number, number];
    onview?: (span: [number, number]) => void;
  } = $props();

  const lo = $derived(view?.[0] ?? from);
  const hi = $derived(view?.[1] ?? to);
  const zoomed = $derived(hi - lo < to - from);
  let open = $state(false);

  let el: HTMLDivElement;
  let width = $state(600);
  // Expanded, the chart fills whatever height its box is given.
  let boxH = $state(0);
  const plotH = $derived(mode === "expanded" ? Math.max(160, boxH) : height);
  // Dense readings are averaged to about one point per 3 px of the visible
  // span, so zooming in brings back every reading.
  const step = $derived(stepFor(hi - lo, width - AXIS_W - PAD_R));
  const shown = $derived(bucket(data, step));
  const tipShown = $derived(tipData && bucket(tipData, step));
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
        const x0 = u.valToPos(Math.max(s, lo), "x", true);
        const x1 = u.valToPos(Math.min(e, hi), "x", true);
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
      ctx.lineWidth = LINE_THIN * dpr;
      ctx.beginPath();
      ctx.moveTo(x, u.bbox.top);
      ctx.lineTo(x, u.bbox.top + u.bbox.height);
      ctx.stroke();
      if (mode !== "overview") {
        ctx.fillStyle = css("--ink-2");
        ctx.font = `500 ${11 * dpr}px ${css("--f-sans")}`;
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillText("Now", x + 4 * dpr, u.bbox.top + 2 * dpr);
      }
    }
    if (yRule && mode !== "overview") {
      const y = Math.round(u.valToPos(yRule.value, "y", true));
      ctx.strokeStyle = css("--ink-3");
      ctx.lineWidth = LINE_THIN * dpr;
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
        const ys = (tipShown ?? u.data)[k + 1];
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

  // A mouse drag across the expanded chart zooms to it; the selection box
  // is cleared at once since the zoom itself shows the result.
  function select(u: uPlot) {
    const { left, width: w } = u.select;
    if (w > 4) {
      const a = u.posToVal(left, "x");
      const b = u.posToVal(left + w, "x");
      onview?.([a, Math.max(b, a + MIN_SPAN)]);
    }
    if (w > 0) u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
  }

  const fit = () => mode === "expanded" && zoomed && !series.some((s) => s.fill || s.area);

  function opts(w: number, h: number): uPlot.Options {
    const axis = {
      stroke: css("--ink-3"),
      grid: { stroke: css("--rule"), width: 1 },
      ticks: { show: false },
      font: `11px ${css("--f-sans")}`,
    };
    const mini = mode === "overview";
    return {
      width: w,
      height: h,
      cursor: mini
        ? { show: false }
        : {
            // Only the dashboard's own charts follow each other.
            sync: mode === "inline" ? { key: "timeline" } : undefined,
            y: false,
            // Stacked areas carry their values in the tooltip; dots on each
            // layer edge would only clutter the stack.
            points: { show: !series.some((s) => s.area), size: 8, width: 2, fill: css("--panel") },
            drag: { x: mode === "expanded", y: false, setScale: false },
            bind: { dblclick: () => () => null },
          },
      legend: { show: false },
      padding: [6, PAD_R, 0, 0],
      scales: {
        x: { time: true, range: () => [lo, hi] },
        // A fixed floor and a fallback ceiling keep the y-axis, and with it
        // the time axis, in place when a chart has no data yet.
        // Zoomed in, line charts fit the visible values; areas keep their zero.
        y: {
          range: (_u, min, max) => {
            if (fit() && min != null && max != null) {
              const [a, b] = uPlot.rangeNum(min, max, 0.1, true);
              return [Math.max(0, a ?? 0), yMax != null ? Math.min(yMax, b ?? yMax) : b];
            }
            return yMax != null ? [0, yMax] : uPlot.rangeNum(0, max ?? 1, 0.1, true);
          },
        },
      },
      axes: [
        {
          ...axis,
          grid: { show: false },
          size: 28,
          splits: (u) => (zoomed ? timeTicks(lo, hi, u.width) : hourTicks(lo, hi, u.width)),
          values: (_u, ticks) => ticks.map(tickLabel),
        },
        // The overview keeps the y-axis gutter blank so its time axis lines up.
        { ...axis, size: AXIS_W, ...(mini && { values: () => [], grid: { show: false } }) },
      ],
      series: [
        {},
        ...series.map((s) => ({
          label: s.label,
          // Stacked areas are edged in their own color, so layers meet cleanly.
          stroke: s.ramp ? rampStroke(s.ramp) : css(s.color),
          fill: s.fill ? css(s.fill) : undefined,
          dash: s.dash,
          width: mini ? LINE_THIN : (s.width ?? (s.area ? LINE_THIN : LINE)),
          spanGaps: false,
          points: { show: false },
        })),
      ],
      hooks: {
        drawClear: [bands],
        draw: [overlays],
        setCursor: [setCursor],
        setSelect: [select],
      },
    };
  }

  let plot: uPlot | undefined;
  // Everything that shapes the plot itself; when this changes it is rebuilt.
  const shape = $derived(JSON.stringify([series, yMax, mode, theme.version]));

  $effect(() => {
    shape;
    const u = untrack(
      () => new uPlot(opts(width, plotH), shown as unknown as uPlot.AlignedData, el),
    );
    u.over.addEventListener("dblclick", () => onview?.([from, to]));
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

  // New readings, a moved time axis or a new zoom: same plot, new data and scales.
  $effect(() => {
    const d = shown as unknown as uPlot.AlignedData;
    lo;
    hi;
    untrack(() => plot?.setData(d));
  });

  $effect(() => {
    const [w, h] = [width, plotH];
    untrack(
      () =>
        plot && (plot.width !== w || plot.height !== h) && plot.setSize({ width: w, height: h }),
    );
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

<figure aria-label={label} class={mode}>
  {#if mode !== "overview"}
    <div class="top">
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
                stroke-width={s.width ?? LINE}
                stroke-dasharray={s.dash?.join(" ")}
              /></svg
            >
            {/if}{s.label}
          </li>
        {/each}
      </ul>
      {#if title && mode === "inline"}
        <button
          type="button"
          class="expand"
          aria-label="Expand {title}"
          title="Expand"
          onclick={() => (open = true)}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"
            ><path d="M8.5 1.5h4v4M12.5 1.5 8 6M5.5 12.5h-4v-4M1.5 12.5 6 8" /></svg
          >
        </button>
      {/if}
    </div>
  {/if}
  <div class="chart" bind:this={el} bind:clientWidth={width} bind:clientHeight={boxH}>
    {#if tip}
      {@const t = tip}
      <Tooltip
        x={t.x}
        y={Math.max(0, Math.min(t.y, plotH - 40 - 22 * series.length))}
        flip={t.x > width - 200}
        title={fmtDayClock(t.t)}
        rows={tipRows(t.values)}
      />
    {/if}
  </div>
</figure>

{#if open && title}
  <ChartDialog
    {title}
    chart={{ data, series, from, to, now, windows, yMax, yRule, label, tipData, shade }}
    onclose={() => (open = false)}
  />
{/if}

<style>
  figure {
    margin: 0;
    min-width: 0;
  }
  .top {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin: 0 0 6px;
  }
  .legend {
    flex: 1;
    list-style: none;
    margin: 0;
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
  .expand {
    flex: none;
    display: grid;
    place-items: center;
    width: 28px;
    height: 28px;
    margin: -7px -6px -7px 0;
    padding: 0;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--ink-3);
    cursor: pointer;
  }
  .expand:hover {
    color: var(--ink);
    background: var(--panel-2);
  }
  .expand:focus-visible {
    outline: 2px solid var(--grid);
    outline-offset: 1px;
  }
  .expand path {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .expanded :global(.u-select) {
    background: color-mix(in srgb, var(--ink) 10%, transparent);
  }
  figure.expanded {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .expanded .chart {
    flex: 1 1 0;
    min-height: 0;
    overflow: hidden;
  }
  .expanded :global(.u-over) {
    cursor: crosshair;
  }
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
</style>
