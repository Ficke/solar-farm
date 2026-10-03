<script lang="ts">
  import type { Daily } from "./api";

  let { days }: { days: Daily["days"] } = $props();
  let width = $state(400);
  const H = 170;
  const M = { l: 40, r: 6, t: 8, b: 22 };

  const rows = $derived(days.slice(-7));
  const ymax = $derived(Math.max(500, ...rows.flatMap((d) => [d.solar_wh, d.grid_wh])) * 1.1);
  const ticks = $derived.by(() => {
    const step = ymax > 2500 ? 1000 : 500;
    return Array.from({ length: Math.floor(ymax / step) + 1 }, (_, i) => i * step);
  });
  const y = (v: number) => M.t + (1 - v / ymax) * (H - M.t - M.b);
  const gw = $derived((width - M.l - M.r) / Math.max(rows.length, 1));
  const bw = $derived(Math.min(18, (gw - 10) / 2));

  function bar(x0: number, v: number) {
    const top = y(v);
    const h = y(0) - top;
    const r = Math.min(4, h, bw / 2);
    return `M${x0},${top + h}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + bw - r}Q${x0 + bw},${top} ${x0 + bw},${top + r}V${top + h}Z`;
  }
  const label = (d: string) =>
    new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });
</script>

<div bind:clientWidth={width}>
  {#if rows.length}
    <svg viewBox="0 0 {width} {H}" height={H} role="img" aria-label="Solar and grid energy per day">
      {#each ticks as v (v)}
        <line x1={M.l} x2={width - M.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
        <text x={M.l - 6} y={y(v) + 4} text-anchor="end" class="tick">{v ? `${v / 1000}k` : "0"}</text>
      {/each}
      {#each rows as d, i (d.day)}
        {@const cx = M.l + gw * i + gw / 2}
        <path d={bar(cx - bw - 1, d.solar_wh)} fill="var(--solar)"><title>{d.day}: solar {d.solar_wh} Wh</title></path>
        <path d={bar(cx + 1, d.grid_wh)} fill="var(--grid)"><title>{d.day}: grid {d.grid_wh} Wh</title></path>
        <text x={cx} y={H - 6} text-anchor="middle" class="tick">{label(d.day)}</text>
      {/each}
    </svg>
  {:else}
    <p class="empty">Daily totals appear after the first day of readings.</p>
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
