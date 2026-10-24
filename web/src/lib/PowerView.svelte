<script lang="ts">
  import type { Window } from "./api";
  import Button from "./Button.svelte";
  import ChartDialog from "./ChartDialog.svelte";
  import { niceTicks } from "./co2";
  import Hint from "./Hint.svelte";
  import { LINE_THIN } from "./layout";
  import TimeChart, { type Series } from "./TimeChart.svelte";
  import { PEAK_HOURS } from "./time";

  let {
    data,
    from,
    to,
    now,
    windows,
  }: {
    data: (number | null | undefined)[][];
    from: number;
    to: number;
    now: number;
    windows: Window[];
  } = $props();
  let open = $state(false);
  const series: Series[] = [
    { label: "Solar", color: "--solar", fill: "--solar-fill", unit: "W" },
    { label: "Grid", color: "--grid", fill: "--grid-fill", unit: "W" },
    { label: "Connected load", color: "--load", width: LINE_THIN, unit: "W" },
    { label: "Battery overhead", color: "--overhead", width: LINE_THIN, unit: "W" },
  ];
  // Matching scales preserve magnitude comparisons between the two panels.
  const yMax = $derived.by(() => {
    let max = 1;
    for (const ys of data.slice(1)) for (const v of ys) if (v != null) max = Math.max(max, v);
    return niceTicks(0, max, 4).at(-1) ?? 1;
  });
  const chart = $derived({
    data,
    series,
    from,
    to,
    now,
    windows,
    yMax,
    label: "Power supply and consumption, W",
  });
</script>

<div class="head">
  <h3>Power activity <span>Past 24 h</span></h3>
  <Button onclick={() => (open = true)}>Expand power activity</Button>
</div>
<div class="panels">
  <section aria-label="Power supply">
    <h4>Supply <span>W</span></h4>
    <TimeChart {...chart} data={[data[0], ...data.slice(1, 3)]} series={series.slice(0, 2)} label="Solar and grid supply, past 24 hours, W" height={140} />
  </section>
  <section aria-label="Power consumption">
    <h4><Hint text="Connected load is the estimated power used by appliances on the Jackery’s outputs. Battery overhead is the Jackery’s own draw.">Consumption</Hint> <span>W</span></h4>
    <TimeChart {...chart} data={[data[0], ...data.slice(3)]} series={series.slice(2)} label="Connected load and battery overhead, past 24 hours, W" height={140} />
  </section>
</div>
<p class="key"><span><i class="grid"></i>Grid use</span><span><i class="peak"></i>Peak, {PEAK_HOURS}</span><span>Matching watt scales</span></p>

{#if open}
  <ChartDialog title="Power activity, W" {chart} splitAt={2} panelTitles={["Supply", "Consumption"]} onclose={() => (open = false)} />
{/if}

<style>
  .head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; margin-bottom: var(--space-4); }
  h3, h4 { margin: 0; font: 500 var(--text-control) var(--f-sans); color: var(--ink-2); }
  h3 span, h4 span { margin-left: 6px; font-size: var(--text-meta); font-weight: 400; color: var(--ink-3); }
  .panels { display: grid; gap: var(--space-4); }
  section { min-width: 0; }
  h4 { margin-bottom: 6px; }
  .key { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: var(--text-meta); color: var(--ink-3); margin: 8px 0 0; }
  .key span { display: inline-flex; align-items: center; gap: 6px; }
  .key i { width: 12px; height: 10px; border-radius: var(--radius-key); }
  .grid { background: var(--plan-band); box-shadow: inset 0 -2px 0 var(--grid); }
  .peak { background: repeating-linear-gradient(-45deg, var(--peak-hatch) 0 1.5px, transparent 1.5px 4px); box-shadow: inset 0 0 0 1px var(--peak-hatch); }
</style>
