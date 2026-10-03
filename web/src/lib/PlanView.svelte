<script lang="ts">
  // The whole plan in one place: a strip of the next day with the charging
  // windows and the peak, then the windows as a list.
  import type { Window } from "./api";
  import { fmtClock, fmtRange, fmtWhen, hours, localMinutes, peakWindows } from "./time";

  let {
    windows,
    forecast,
    now,
    generatedAt,
  }: {
    windows: Window[];
    forecast: [number, number][];
    now: number;
    generatedAt: number | null;
  } = $props();

  let width = $state(600);
  const H = 64;
  const PAD = 8;
  const from = $derived(now - 2 * 3600);
  const to = $derived(now + 24 * 3600);
  const x = (t: number) => PAD + ((t - from) / (to - from)) * (width - 2 * PAD);

  const ticks = $derived.by(() => {
    const out: number[] = [];
    let t = from - (from % 3600) + 3600;
    for (; t < to; t += 3600) if (localMinutes(t) % (width < 500 ? 360 : 180) === 0) out.push(t);
    return out;
  });

  const avg = (s: number, e: number) => {
    const vs = forecast.filter(([t]) => t >= s && t < e).map(([, v]) => v);
    return vs.length ? Math.round(vs.reduce((a, b) => a + b, 0) / vs.length) : null;
  };

  const rows = $derived(
    windows
      .filter(([, e]) => e > now - 6 * 3600)
      .map(([s, e], i, all) => {
        const nextIdx = all.findIndex(([, ee]) => ee > now);
        const state = e <= now ? "Done" : s <= now ? "Now" : i === nextIdx ? "Next" : "Later";
        return { s, e, state, avg: avg(s, e) };
      }),
  );
  const planned = $derived(
    windows.reduce((sum, [s, e]) => sum + Math.max(0, e - Math.max(s, now)), 0),
  );
</script>

<div class="strip" bind:clientWidth={width}>
  <svg viewBox="0 0 {width} {H}" height={H} role="img" aria-label="Grid charging over the next 24 hours">
    <rect x={PAD} y="8" width={width - 2 * PAD} height="28" rx="6" fill="var(--panel-2)" />
    {#each peakWindows(from, to) as [s, e] (s)}
      <rect
        x={x(Math.max(s, from))}
        y="8"
        width={x(Math.min(e, to)) - x(Math.max(s, from))}
        height="28"
        fill="var(--peak-band)"
      />
    {/each}
    {#each windows as [s, e] (s)}
      {#if e > from && s < to}
        <rect
          x={x(Math.max(s, from)) + 1}
          y="10"
          width={Math.max(2, x(Math.min(e, to)) - x(Math.max(s, from)) - 2)}
          height="24"
          rx="4"
          fill="var(--grid)"
          opacity={e <= now ? 0.45 : 1}
        ><title>{fmtRange(s, e)} grid on</title></rect>
      {/if}
    {/each}
    <line x1={x(now)} x2={x(now)} y1="2" y2="42" stroke="var(--ink)" stroke-width="1.5" />
    {#each ticks as t (t)}
      <text x={x(t)} y={H - 6} text-anchor="middle" class="tick"
        >{localMinutes(t) === 0 ? fmtWhen(t, now).split(" ")[0] : fmtClock(t)}</text
      >
    {/each}
  </svg>
  <p class="key">
    <span><i class="sw on"></i>Grid on</span>
    <span><i class="sw peak"></i>PG&amp;E peak, always off</span>
    <span><i class="sw now"></i>Now</span>
  </p>
</div>

{#if rows.length}
  <table>
    <thead>
      <tr><th>When</th><th>Length</th><th>Forecast emissions</th><th></th></tr>
    </thead>
    <tbody>
      {#each rows as r (r.s)}
        <tr class:done={r.state === "Done"}>
          <td>{fmtWhen(r.s, now).replace(fmtClock(r.s), "")}{fmtRange(r.s, r.e)}</td>
          <td>{hours(r.e - r.s)}</td>
          <td>{r.avg == null ? "–" : `${r.avg} lb/MWh`}</td>
          <td><span class="state {r.state.toLowerCase()}">{r.state}</span></td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else}
  <p class="muted">No grid charging is planned in the next 24 hours.</p>
{/if}

<p class="muted foot">
  {hours(Math.round(planned / 1800) * 1800)} of grid charging left in this plan.
  {#if generatedAt}Made at {fmtClock(generatedAt)} from WattTime's 24-hour forecast.{/if}
  The plan is rebuilt every 30 minutes, so windows can move.
</p>
<details>
  <summary>How the plug decides</summary>
  <ol>
    <li>4–9 PM: always off (PG&amp;E peak).</li>
    <li>Off for 30 hours straight: on for 2 hours so the battery can't run flat.</li>
    <li>A plan less than 3 hours old: on inside its windows.</li>
    <li>Otherwise WattTime's live index: on when the grid is cleaner than 75% of the past month.</li>
    <li>No internet: on from 10 AM to 3 PM.</li>
  </ol>
</details>

<style>
  .strip svg {
    display: block;
    width: 100%;
  }
  .tick {
    font: 11px var(--f-body);
    fill: var(--ink-3);
  }
  .key {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    margin: 2px 0 10px;
    font-size: 12px;
    color: var(--ink-2);
  }
  .key span {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .sw {
    display: inline-block;
    width: 12px;
    height: 10px;
    border-radius: 2px;
  }
  .sw.on {
    background: var(--grid);
  }
  .sw.peak {
    background: var(--peak-band);
    outline: 1px solid var(--peak-ink);
    outline-offset: -1px;
  }
  .sw.now {
    width: 2px;
    background: var(--ink);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    font-variant-numeric: tabular-nums;
  }
  th {
    text-align: left;
    font-weight: 500;
    font-size: 12px;
    color: var(--ink-3);
    padding: 4px 8px 4px 0;
  }
  td {
    padding: 8px 8px 8px 0;
    border-top: 1px solid var(--line);
  }
  tr.done td {
    color: var(--ink-3);
  }
  .state {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--panel-2);
    color: var(--ink-2);
  }
  .state.now,
  .state.next {
    background: var(--grid-fill);
    color: var(--ink);
    font-weight: 600;
  }
  .muted {
    color: var(--ink-3);
    font-size: 13px;
  }
  .foot {
    margin: 10px 0 6px;
  }
  details {
    font-size: 13px;
    color: var(--ink-2);
  }
  summary {
    cursor: pointer;
    color: var(--accent);
  }
  ol {
    margin: 6px 0 0;
    padding-left: 20px;
  }
</style>
