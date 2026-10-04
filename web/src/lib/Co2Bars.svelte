<script lang="ts">
  // CO2 avoided per period. Bars below zero are periods where charging
  // losses outweighed the cleaner hours.
  import type { Co2 } from "./api";
  import { fmtLb, periodLabel } from "./co2";

  let { periods, by }: { periods: Co2["periods"]; by: Co2["by"] } = $props();
  let width = $state(400);
  const H = 150;
  const M = { l: 40, r: 6, t: 8, b: 22 };

  const values = $derived(periods.map((p) => p.avoided_lb));
  const step = $derived.by(() => {
    const span = Math.max(0.1, ...values.map(Math.abs));
    const raw = span / 3;
    const mag = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  });
  const lo = $derived(Math.min(0, Math.floor(Math.min(...values, 0) / step)) * step);
  const hi = $derived(Math.max(step, Math.ceil(Math.max(...values, 0) / step) * step));
  const ticks = $derived(
    Array.from({ length: Math.round((hi - lo) / step) + 1 }, (_, i) => lo + i * step),
  );
  const y = (v: number) => M.t + ((hi - v) / (hi - lo)) * (H - M.t - M.b);
  const gw = $derived((width - M.l - M.r) / Math.max(periods.length, 1));
  const bw = $derived(Math.min(22, gw - 6));
  // Skip labels when they'd collide.
  const every = $derived(Math.max(1, Math.ceil(44 / gw)));
</script>

<div bind:clientWidth={width}>
  {#if periods.length}
    <svg viewBox="0 0 {width} {H}" height={H} role="img" aria-label="CO2 avoided per {by}">
      {#each ticks as v (v)}
        <line x1={M.l} x2={width - M.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
        <text x={M.l - 6} y={y(v) + 4} text-anchor="end" class="tick">{+v.toFixed(2)}</text>
      {/each}
      {#each periods as p, i (p.start)}
        {@const cx = M.l + gw * i + gw / 2}
        {@const top = y(Math.max(0, p.avoided_lb))}
        <rect
          x={cx - bw / 2}
          y={top}
          width={bw}
          height={Math.max(1, Math.abs(y(p.avoided_lb) - y(0)))}
          rx="2"
          fill={p.avoided_lb < 0 ? "var(--bad)" : "var(--good)"}
          ><title
            >{periodLabel(p.start, by)}: {fmtLb(p.avoided_lb)} lb avoided ({fmtLb(p.load_lb)} without battery, {fmtLb(
              p.grid_lb,
            )} from the plug)</title
          ></rect
        >
        {#if (periods.length - 1 - i) % every === 0}
          <text x={cx} y={H - 6} text-anchor="middle" class="tick">{periodLabel(p.start, by)}</text>
        {/if}
      {/each}
      <line x1={M.l} x2={width - M.r} y1={y(0)} y2={y(0)} stroke="var(--ink-3)" />
    </svg>
  {:else}
    <p class="empty">No totals yet.</p>
  {/if}
</div>

<style>
  svg {
    display: block;
    width: 100%;
  }
  .tick {
    font: 11px var(--f-mono);
    fill: var(--ink-3);
  }
  .empty {
    color: var(--ink-3);
    font-size: 13px;
  }
</style>
