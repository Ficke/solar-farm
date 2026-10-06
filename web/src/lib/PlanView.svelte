<script lang="ts">
  import type { Sample, Window } from "./api";
  import Hint from "./Hint.svelte";
  import { hover } from "./hover.svelte";
  import { AXIS_W, hourTicks, LINE_THIN, PAD_R } from "./layout";
  import {
    blockAt,
    fromWindows,
    KEY,
    MODES,
    type PlanBlock,
    ROUND_TRIP,
    type Segment,
    segments,
  } from "./plan";
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

  let {
    windows,
    blocks,
    states,
    samples,
    forecast,
    from,
    to,
    now,
  }: {
    windows: Window[];
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
  function leave() {
    hover.t = null;
    hover.from = "plan";
  }

  const segs = $derived(blocks.length ? segments(blocks) : fromWindows(windows));
  const sampleAt = (t: number) => {
    let best: Sample | null = null;
    for (const p of samples) {
      if (Math.abs(p.t - t) <= 600 && (!best || Math.abs(p.t - t) < Math.abs(best.t - t))) best = p;
    }
    return best;
  };
  const forecastAt = (t: number) => {
    let co2: number | null = null;
    let best = 600;
    for (const [ft, v] of forecast) {
      if (Math.abs(ft - t) <= best) {
        best = Math.abs(ft - t);
        co2 = v;
      }
    }
    return co2;
  };
  const lb = (v: number) => `${Math.round(v)} lb/MWh`;

  const tip = $derived.by(() => {
    const t = hover.t;
    if (t == null || hover.from !== "plan") return null;
    if (t < now) {
      const g = states.find((g) => t >= g.s && t < g.e);
      const p = sampleAt(t);
      const rows: TipRow[] = [
        g
          ? { value: MODES[g.mode].label, color: `var(--plan-${g.mode})`, shape: "square" }
          : { value: "No data" },
      ];
      if (p?.moer != null) rows.push({ value: lb(p.moer), name: "CO₂" });
      if (p?.battery_pct != null)
        rows.push({ value: `${Math.round(p.battery_pct)}%`, name: "Battery" });
      return { t, rows };
    }
    const b = blockAt(blocks, t);
    const peak = peakWindows(from, to).some(([s, e]) => t >= s && t < e);
    const on = segs.some((g) => MODES[g.mode].on && t >= g.s && t < g.e);
    const mode = b?.mode ?? (on ? "charge" : peak ? "peak" : null);
    const co2 = b?.moer ?? forecastAt(t);
    const rows: TipRow[] = [
      mode
        ? { value: MODES[mode].label, color: `var(--plan-${mode})`, shape: "square" }
        : { value: "Grid off" },
    ];
    if (co2 != null) rows.push({ value: lb(co2), name: "CO₂ forecast" });
    if (b?.recharge != null)
      rows.push({ value: lb(b.recharge / ROUND_TRIP), name: "Recharge later, with losses" });
    if (b) rows.push({ value: `${Math.round(b.pct)}%`, name: "Battery" });
    if (mode === "solar") rows.push({ name: "Room kept for solar" });
    return { t, rows };
  });

  const rows = $derived.by(() => {
    const on = segs.filter((g) => MODES[g.mode].on && g.e > now);
    const next = on.find((g) => g.s > now);
    return on.map((g) => ({ ...g, state: g.s <= now ? "Now" : g === next ? "Next" : "" }));
  });
</script>

<div class="strip" bind:clientWidth={width}>
  <svg
    viewBox="0 0 {width} {H}"
    height={H}
    role="img"
    aria-label="Plug states, past 24 hours and plan for the next 24"
    onpointermove={move}
    onpointerleave={leave}
  >
    <defs>
      <pattern id="peak-hatch" width="6" height="6" patternUnits="userSpaceOnUse">
        <path d="M-1,7 L7,-1" stroke="var(--peak-hatch)" stroke-width="1.5" />
      </pattern>
    </defs>
    <rect x={AXIS_W} y="8" width={Math.max(0, width - AXIS_W - PAD_R)} height="20" rx="4" fill="var(--panel-2)" />
    {#each peakWindows(from, to) as [s, e] (s)}
      {@const [a, b] = clip(s, e)}
      {#if b > a}<rect x={a} y="8" width={b - a} height="20" fill="url(#peak-hatch)" />{/if}
    {/each}
    {#each states as g, i (i)}
      {#if g.e > from && g.s < to && MODES[g.mode].on}
        {@const [a, b] = clip(g.s, g.e)}
        <rect x={a} y="10" width={Math.max(2, b - a)} height="16" rx="3" fill="var(--plan-{g.mode})"
          ><title>{MODES[g.mode].label}, {fmtRange(g.s, g.e)}</title></rect
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
  <table>
    <thead>
      <tr><th>Time</th><th>Length</th><th>Mode</th><th>CO₂</th><th></th></tr>
    </thead>
    <tbody>
      {#each rows as r (r.s)}
        <tr>
          <td>{fmtWhen(r.s, now).replace(fmtClock(r.s), "")}{fmtRange(r.s, r.e)}</td>
          <td>{hours(r.e - r.s)}</td>
          <td>{MODES[r.mode].label}</td>
          <td>{r.moer == null ? "" : lb(r.moer)}</td>
          <td class="st">{#if r.state}<span class={r.state.toLowerCase()}>{r.state}</span>{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table>
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
  }
  .tick {
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
    border-radius: 2px;
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
