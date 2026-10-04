<script lang="ts">
  import type { Window } from "./api";
  import { hover } from "./hover.svelte";
  import { AXIS_W, hourTicks, LINE_THIN, PAD_R } from "./layout";
  import Tooltip from "./Tooltip.svelte";
  import {
    fmtClock,
    fmtDayClock,
    fmtRange,
    fmtWeekday,
    fmtWhen,
    hours,
    localMinutes,
    peakWindows,
  } from "./time";

  let {
    windows,
    forecast,
    from,
    to,
    now,
  }: {
    windows: Window[];
    forecast: [number, number][];
    from: number;
    to: number;
    now: number;
  } = $props();

  let width = $state(600);
  const H = 52;
  const x = (t: number) => AXIS_W + ((t - from) / (to - from)) * (width - AXIS_W - PAD_R);
  const clip = (s: number, e: number) => [x(Math.max(s, from)), x(Math.min(e, to))];

  const span = () => width - AXIS_W - PAD_R;

  function move(e: PointerEvent) {
    const px = e.clientX - (e.currentTarget as Element).getBoundingClientRect().left;
    const t = from + ((px - AXIS_W) / span()) * (to - from);
    hover.t = t >= from && t <= to ? t : null;
    hover.from = "plan";
  }
  function leave() {
    hover.t = null;
    hover.from = "plan";
  }

  const tip = $derived.by(() => {
    const t = hover.t;
    if (t == null || hover.from !== "plan") return null;
    const on = windows.some(([s, e]) => t >= s && t < e);
    const peak = peakWindows(from, to).some(([s, e]) => t >= s && t < e);
    let co2: number | null = null;
    let best = 600;
    for (const [ft, v] of forecast) {
      if (Math.abs(ft - t) <= best) {
        best = Math.abs(ft - t);
        co2 = Math.round(v);
      }
    }
    return { t, state: on ? "Grid on" : peak ? "Peak, grid off" : "Grid off", co2 };
  });

  const avg = (s: number, e: number) => {
    const vs = forecast.filter(([t]) => t >= s && t < e).map(([, v]) => v);
    return vs.length ? Math.round(vs.reduce((a, b) => a + b, 0) / vs.length) : null;
  };
  const rows = $derived.by(() => {
    const next = windows.findIndex(([, e]) => e > now);
    return windows
      .filter(([, e]) => e > now - 6 * 3600)
      .map(([s, e]) => {
        const i = windows.findIndex(([ws]) => ws === s);
        const state = e <= now ? "Done" : s <= now ? "Now" : i === next ? "Next" : "";
        return { s, e, state, avg: avg(s, e) };
      });
  });
</script>

<div class="strip" bind:clientWidth={width}>
  <svg
    viewBox="0 0 {width} {H}"
    height={H}
    role="img"
    aria-label="Grid on times, past and next 24 hours"
    onpointermove={move}
    onpointerleave={leave}
  >
    <defs>
      <pattern id="peak-hatch" width="6" height="6" patternUnits="userSpaceOnUse">
        <path d="M-1,7 L7,-1" stroke="var(--peak-hatch)" stroke-width="1.5" />
      </pattern>
    </defs>
    <text x={AXIS_W - 8} y="22" text-anchor="end" class="lab">Grid</text>
    <rect x={AXIS_W} y="8" width={Math.max(0, width - AXIS_W - PAD_R)} height="20" rx="4" fill="var(--panel-2)" />
    {#each peakWindows(from, to) as [s, e] (s)}
      {@const [a, b] = clip(s, e)}
      {#if b > a}<rect x={a} y="8" width={b - a} height="20" fill="url(#peak-hatch)" />{/if}
    {/each}
    {#each windows as [s, e] (s)}
      {#if e > from && s < to}
        {@const [a, b] = clip(s, e)}
        <rect x={a} y="10" width={Math.max(2, b - a)} height="16" rx="3" fill="var(--grid)"
          ><title>{fmtRange(s, e)}</title></rect
        >
      {/if}
    {/each}
    <line x1={x(now)} x2={x(now)} y1="4" y2="32" stroke="var(--ink)" stroke-width={LINE_THIN} />
    {#if hover.t != null}
      <line x1={x(hover.t)} x2={x(hover.t)} y1="4" y2="32" stroke="var(--ink-2)" stroke-width={LINE_THIN} stroke-dasharray="3 3" />
    {/if}
    {#each hourTicks(from, to, width) as t (t)}
      <text x={x(t)} y={H - 4} text-anchor="middle" class="tick"
        >{localMinutes(t) === 0 ? fmtWeekday(t) : fmtClock(t)}</text
      >
    {/each}
  </svg>
  {#if tip}
    <Tooltip
      x={x(tip.t)}
      y={36}
      flip={x(tip.t) > width - 200}
      title={fmtDayClock(tip.t)}
      rows={[
        { value: tip.state },
        ...(tip.co2 != null ? [{ value: `${tip.co2} lb/MWh`, name: "Forecast" }] : []),
      ]}
    />
  {/if}
</div>

{#if rows.length}
  <table>
    <tbody>
      {#each rows as r (r.s)}
        <tr class:done={r.state === "Done"}>
          <td>{fmtWhen(r.s, now).replace(fmtClock(r.s), "")}{fmtRange(r.s, r.e)}</td>
          <td>{hours(r.e - r.s)}</td>
          <td>{r.avg == null ? "" : `${r.avg} lb/MWh`}</td>
          <td class="st">{#if r.state}<span class={r.state.toLowerCase()}>{r.state}</span>{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else}
  <p class="muted">No grid charging planned.</p>
{/if}

<style>
  .strip {
    position: relative;
  }
  svg {
    display: block;
    width: 100%;
    touch-action: pan-y;
  }
  .tick,
  .lab {
    font: 11px var(--f-sans);
    fill: var(--ink-3);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
    font-size: 14px;
    font-variant-numeric: tabular-nums;
  }
  td {
    padding: 7px 8px 7px 0;
    border-top: 1px solid var(--rule);
  }
  td:nth-child(2),
  td:nth-child(3) {
    color: var(--ink-2);
  }
  tr.done td {
    color: var(--ink-3);
  }
  .st {
    text-align: right;
  }
  .st span {
    font-size: 13px;
    color: var(--ink-3);
  }
  .st .now,
  .st .next {
    color: var(--grid);
    font-weight: 600;
  }
  .muted {
    color: var(--ink-3);
    font-weight: 400;
  }
</style>
