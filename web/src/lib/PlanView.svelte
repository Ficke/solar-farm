<script lang="ts">
  import { nearest } from "./align";
  import type { Sample } from "./api";
  import Hint from "./Hint.svelte";
  import { hover } from "./hover.svelte";
  import { AXIS_W, hourTicks, LINE_THIN, PAD_R } from "./layout";
  import { blockAt, KEY, MODES, type PlanBlock, type Segment, stateAt } from "./plan";
  import Tooltip, { type TipRow } from "./Tooltip.svelte";
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
  import { holdTouch } from "./touch";
  import { fmtRate } from "./units";

  let {
    blocks,
    states,
    samples,
    forecast,
    from,
    to,
    now,
  }: {
    blocks: PlanBlock[];
    /** Past and planned plug states, shared with the chart bands. */
    states: Segment[];
    samples: Sample[];
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
  function clear() {
    hover.t = null;
    hover.from = "plan";
  }
  // Touch readouts stay after the finger lifts; see touch.ts.
  function leave(e: PointerEvent) {
    if (e.pointerType !== "touch") clear();
  }
  function lift(e: PointerEvent) {
    if (e.pointerType === "touch") holdTouch(e.currentTarget as Element, clear);
  }

  const tip = $derived.by(() => {
    const t = hover.t;
    if (t == null || hover.from !== "plan") return null;
    const g = stateAt(states, t);
    const peak = peakWindows(from, to).some(([s, e]) => t >= s && t < e);
    const mode = g?.mode ?? (t >= now && peak ? "peak" : null);
    const rows: TipRow[] = [
      mode
        ? { value: MODES[mode].label, color: `--plan-${mode}`, shape: "square" }
        : { value: t < now ? "No data" : "Grid off" },
    ];
    if (t < now) {
      const p = nearest(samples, t, (p) => p.t);
      if (p?.moer != null) rows.push({ value: fmtRate(p.moer), name: "CO₂" });
      if (p?.battery_pct != null)
        rows.push({ value: `${Math.round(p.battery_pct)}%`, name: "Battery" });
      return { t, rows };
    }
    const b = blockAt(blocks, t);
    const co2 = b?.moer ?? nearest(forecast, t, ([ft]) => ft)?.[1];
    if (co2 != null) rows.push({ value: fmtRate(co2), name: "CO₂ forecast" });
    if (b) rows.push({ value: `${Math.round(b.pct)}%`, name: "Battery" });
    if (mode === "solar") rows.push({ name: "Room kept for solar" });
    return { t, rows };
  });

  const rows = $derived.by(() => {
    const on = states.filter((g) => MODES[g.mode].on && g.e > now);
    let next = true;
    return on.map((g) => {
      const state = g.s <= now ? "Now" : next ? "Next" : "";
      if (g.s > now) next = false;
      return { ...g, state };
    });
  });
</script>

<div class="strip" bind:clientWidth={width}>
  <svg
    viewBox="0 0 {width} {H}"
    height={H}
    role="img"
    aria-label="Grid use, past 24 hours and plan for the next 24"
    onpointerdown={move}
    onpointermove={move}
    onpointerup={lift}
    onpointerleave={leave}
    onpointercancel={clear}
  >
    <defs>
      <pattern id="peak-hatch" width="6" height="6" patternUnits="userSpaceOnUse">
        <path d="M-1,7 L7,-1" stroke="var(--peak-hatch)" stroke-width="1.5" />
      </pattern>
    </defs>
    <rect x={AXIS_W} y="8" width={Math.max(0, width - AXIS_W - PAD_R)} height="20" rx="0" fill="var(--panel-2)" />
    {#each peakWindows(from, to) as [s, e] (s)}
      {@const [a, b] = clip(s, e)}
      {#if b > a}<rect x={a} y="8" width={b - a} height="20" fill="url(#peak-hatch)" />{/if}
    {/each}
    {#each states as g, i (i)}
      {#if g.e > from && g.s < to && MODES[g.mode].on}
        {@const [a, b] = clip(g.s, g.e)}
        <rect x={a} y="10" width={Math.max(2, b - a)} height="16" rx="0" fill="var(--plan-{g.mode})"
          ><title>{MODES[g.mode].label}, {fmtRange(g.s, g.e)}</title></rect
        >
      {/if}
    {/each}
    <line x1={x(now)} x2={x(now)} y1="4" y2="32" stroke="var(--ink)" stroke-width={LINE_THIN} />
    <text x={Math.min(width - PAD_R - 28, x(now) + 4)} y="7" class="tick">Now</text>
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
      rows={tip.rows}
    />
  {/if}
</div>

<ul class="key">
  {#each KEY as m (m)}
    <li><i class="sw {m}"></i><Hint text={MODES[m].rule}>{MODES[m].label}</Hint></li>
  {/each}
</ul>

{#if rows.length}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll narrow tables.) -->
  <div class="table-scroll" tabindex="0" role="region" aria-label="Planned grid use">
  <table>
    <thead>
      <tr><th>Time</th><th>Length</th><th>Mode</th><th>CO₂, g/kWh</th><th></th></tr>
    </thead>
    <tbody>
      {#each rows as r (r.s)}
        <tr>
          <td>{#if r.s <= now}Now–{fmtClock(r.e)}{:else}{fmtWhen(r.s, now).replace(fmtClock(r.s), "")}{fmtRange(r.s, r.e)}{/if}</td>
          <td>{hours(r.e - Math.max(now, r.s))}{r.s <= now ? " remaining" : ""}</td>
          <td>{MODES[r.mode].label}</td>
          <td>{r.moer == null ? "" : fmtRate(r.moer)}</td>
          <td class="st">{#if r.state}<span class={r.state.toLowerCase()}>{r.state}</span>{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  </div>
{:else}
  <p class="muted">No grid use planned</p>
{/if}

<style>
  .strip {
    position: relative;
  }
  svg {
    display: block;
    width: 100%;
    touch-action: pan-y;
    -webkit-user-select: none;
    user-select: none;
    -webkit-touch-callout: none;
  }
  .tick {
    font: var(--text-meta) var(--f-sans);
    fill: var(--ink-3);
  }
  .table-scroll { overflow-x: auto; }
  .table-scroll:focus-visible { outline: var(--focus-width) solid var(--grid); outline-offset: 2px; }
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
  th {
    padding: 0 8px 4px 0;
    text-align: left;
    font-size: 12px;
    font-weight: 500;
    color: var(--ink-3);
  }
  td:nth-child(1),
  td:nth-child(2),
  td:nth-child(4) {
    white-space: nowrap;
  }
  td:nth-child(2),
  td:nth-child(3),
  td:nth-child(4) {
    color: var(--ink-2);
  }
  .key {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 20px;
    margin: 4px 0 0;
    padding: 0;
    list-style: none;
    font-size: 12px;
    color: var(--ink-2);
  }
  .key li {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .sw {
    width: 12px;
    height: 10px;
    border-radius: var(--radius-key);
  }
  .sw.charge {
    background: var(--plan-charge);
  }
  .sw.bypass {
    background: var(--plan-bypass);
  }
  .sw.battery {
    background: var(--panel-2);
  }
  .sw.peak {
    background: repeating-linear-gradient(-45deg, var(--peak-hatch) 0 1.5px, transparent 1.5px 4px);
    box-shadow: inset 0 0 0 1px var(--peak-hatch);
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
