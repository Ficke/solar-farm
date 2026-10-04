<script lang="ts">
  // The plan: a strip on the same time axis as the charts, then the windows.
  import type { Window } from "./api";
  import { AXIS_W, hourTicks, PAD_R } from "./layout";
  import {
    fmtClock,
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

<div bind:clientWidth={width}>
  <svg viewBox="0 0 {width} {H}" height={H} role="img" aria-label="Grid on times, past and next 24 hours">
    <text x={AXIS_W - 8} y="22" text-anchor="end" class="lab">Grid</text>
    <rect x={AXIS_W} y="8" width={Math.max(0, width - AXIS_W - PAD_R)} height="20" rx="4" fill="var(--panel-2)" />
    {#each peakWindows(from, to) as [s, e] (s)}
      {@const [a, b] = clip(s, e)}
      {#if b > a}<rect x={a} y="8" width={b - a} height="20" fill="var(--peak-band)" />{/if}
    {/each}
    {#each windows as [s, e] (s)}
      {#if e > from && s < to}
        {@const [a, b] = clip(s, e)}
        <rect x={a} y="10" width={Math.max(2, b - a)} height="16" rx="3" fill="var(--grid)"
          ><title>{fmtRange(s, e)}</title></rect
        >
      {/if}
    {/each}
    <line x1={x(now)} x2={x(now)} y1="4" y2="32" stroke="var(--ink)" stroke-width="1.5" />
    {#each hourTicks(from, to, width) as t (t)}
      <text x={x(t)} y={H - 4} text-anchor="middle" class="tick"
        >{localMinutes(t) === 0 ? fmtWeekday(t) : fmtClock(t)}</text
      >
    {/each}
  </svg>
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

<div class="rules">
  <h3>Rules, in priority order</h3>
  <ol>
    <li>4–9 PM: off</li>
    <li>Off for 30 hours: on for 2 hours</li>
    <li>Plan under 3 hours old: on during its windows</li>
    <li>No current plan: on when cleaner than 75% of the past month</li>
    <li>No internet: on 10 AM–3 PM</li>
  </ol>
</div>

<style>
  svg {
    display: block;
    width: 100%;
  }
  .tick,
  .lab {
    font: 11px var(--f-body);
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
    border-top: 1px solid var(--line);
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
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--panel-2);
    color: var(--ink-3);
  }
  .st .now,
  .st .next {
    background: var(--grid-fill);
    color: var(--ink);
    font-weight: 600;
  }
  .muted {
    color: var(--ink-3);
    font-weight: 400;
  }
  .rules {
    margin-top: 14px;
    font-size: 13px;
    color: var(--ink-2);
  }
  h3 {
    font: 600 13px var(--f-body);
    margin: 0 0 4px;
    color: var(--ink);
  }
  ol {
    margin: 0;
    padding-left: 18px;
    columns: 2 260px;
    column-gap: 24px;
  }
</style>
