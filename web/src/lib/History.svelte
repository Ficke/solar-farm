<script lang="ts">
  // Keep energy and carbon periods aligned across both charts.
  import type { Co2, Period } from "./api";
  import { fmtMass, fmtWh, niceTicks, periodLabel, periodName, type Slot, slots } from "./co2";
  import Hint from "./Hint.svelte";
  import Tooltip, { type TipRow } from "./Tooltip.svelte";
  import { holdTouch } from "./touch";
  import { kg } from "./units";

  let {
    co2,
    now,
    by,
    error = "",
  }: { co2: Co2 | undefined; now: number; by: Period; error?: string } = $props();
  let width = $state(400);
  let hovered = $state<number | null>(null);
  let tipW = $state(0);
  let active = $state<"energy" | "carbon">("energy");

  const cols = $derived(co2 ? slots(co2.periods, co2.by, now) : []);
  const hasReadings = $derived(cols.some(({ p }) => p));
  const M = { l: 44, r: 8 };
  const EH = 200; // energy chart
  const CH = 150; // CO2 chart, with the period labels under it
  const PAD = { t: 8, b: 4 };
  const LABELS = 22;

  const gw = $derived((width - M.l - M.r) / Math.max(cols.length, 1));
  const bw = $derived(Math.max(2, Math.min(16, gw * 0.28)));
  const cx = (i: number) => M.l + gw * i + gw / 2;
  // Skip period labels when they'd collide; always keep the latest.
  const every = $derived(Math.max(1, Math.ceil((by === "month" ? 36 : 48) / gw)));

  // Paired stacks compare supply and use on the same positive scale.
  const eTicks = $derived(
    niceTicks(
      0,
      Math.max(
        0.5,
        ...cols.map(({ p }) => (p ? Math.max(p.solar_wh + p.grid_wh, p.load_wh) / 1000 : 0)),
      ),
      4,
    ),
  );
  const eHi = $derived(eTicks.at(-1) ?? 1);
  const ey = (kwh: number) => PAD.t + ((eHi - kwh) / eHi) * (EH - LABELS - PAD.t - PAD.b);

  // Stack each source's avoided CO2 up from zero; a negative part (CO2
  // added) stacks down.
  const parts = (p: { solar_lb: number; shift_lb: number }) => {
    let up = 0;
    let down = 0;
    const xs = [
      { lb: kg(p.solar_lb), color: "var(--solar)" },
      { lb: kg(p.shift_lb), color: "var(--shift)" },
    ]
      .filter((x) => x.lb !== 0)
      .map((x) => {
        const from = x.lb > 0 ? up : down;
        if (x.lb > 0) up += x.lb;
        else down += x.lb;
        return { ...x, from, to: from + x.lb };
      });
    return xs;
  };
  const cTicks = $derived.by(() => {
    const ps = cols.map(({ p }) => (p ? parts(p) : []));
    const lo = ps.map((xs) => Math.min(0, ...xs.map((x) => x.to)));
    const hi = ps.map((xs) => Math.max(0, ...xs.map((x) => x.to)));
    return niceTicks(Math.min(0, ...lo), Math.max(0.05, ...hi), 3);
  });
  const cLo = $derived(cTicks[0] ?? 0);
  const cHi = $derived(cTicks.at(-1) ?? 1);
  const cy = (v: number) => PAD.t + ((cHi - v) / (cHi - cLo)) * (CH - LABELS - PAD.t - PAD.b);

  const fmtTick = (v: number) => String(+v.toFixed(3));

  const sum = (
    k: "solar_wh" | "grid_wh" | "load_wh" | "overhead_wh" | "avoided_lb" | "solar_lb" | "shift_lb",
  ) => cols.reduce((a, { p }) => a + (p?.[k] ?? 0), 0);
  const totals = $derived({
    supplied: fmtWh(sum("solar_wh") + sum("grid_wh")),
    solar: fmtWh(sum("solar_wh")),
    grid: fmtWh(sum("grid_wh")),
    load: fmtWh(sum("load_wh")),
    appliances: fmtWh(sum("load_wh") - sum("overhead_wh")),
    overhead: fmtWh(sum("overhead_wh")),
    avoided: kg(sum("avoided_lb")),
    solarKg: kg(sum("solar_lb")),
    shiftKg: kg(sum("shift_lb")),
  });

  const tip = $derived<Slot | null>(hovered != null ? (cols[hovered] ?? null) : null);
  const tipX = $derived.by(() => {
    if (hovered == null) return 0;
    const right = cx(hovered) + gw / 2 + 4;
    const left = cx(hovered) - gw / 2 - 4 - tipW;
    const x = right + tipW <= width ? right : left >= 0 ? left : width - tipW;
    return Math.max(0, x);
  });

  function pick(e: PointerEvent) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left - M.l) / gw);
    hovered = i >= 0 && i < cols.length ? i : null;
  }

  function bar(x: number, y0: number, y1: number) {
    if (Math.abs(y0 - y1) < 0.5) return "";
    return `M${x},${y0}V${y1}H${x + bw}V${y0}Z`;
  }
  const co2Label = (v: number) => (v < 0 ? "CO₂ added" : "CO₂ avoided");
  const signed = (v: number) => (v < 0 ? `−${fmtMass(-v)}` : fmtMass(v));
  const span = (wh: [string, string]) => `${wh[0]} ${wh[1]}`;

  function navigate(e: KeyboardEvent) {
    if (e.key === "Escape") {
      hovered = null;
      return;
    }
    if (
      !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(e.key) ||
      !cols.length
    )
      return;
    e.preventDefault();
    hovered =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? cols.length - 1
          : Math.max(
              0,
              Math.min(
                cols.length - 1,
                (hovered ?? cols.length - 1) +
                  (e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 1),
              ),
            );
  }

  function tipRows({ p }: Slot, kind = active): TipRow[] {
    if (!p) return [{ name: "No readings" }];
    if (kind === "carbon")
      return [
        { value: `${fmtMass(Math.abs(kg(p.avoided_lb)))} kg`, name: co2Label(p.avoided_lb) },
        { color: "--solar", value: `${signed(kg(p.solar_lb))} kg`, name: "Solar" },
        { color: "--shift", value: `${signed(kg(p.shift_lb))} kg`, name: "Load shifting" },
      ];
    return [
      { value: span(fmtWh(p.solar_wh + p.grid_wh)), name: "Energy supplied" },
      { color: "--solar", value: span(fmtWh(p.solar_wh)), name: "Solar" },
      { color: "--grid", value: span(fmtWh(p.grid_wh)), name: "Grid" },
      { value: span(fmtWh(p.load_wh)), name: "Consumption" },
      { color: "--load", value: span(fmtWh(p.load_wh - p.overhead_wh)), name: "Connected load" },
      { color: "--overhead", value: span(fmtWh(p.overhead_wh)), name: "Battery overhead" },
    ];
  }
</script>

{#snippet dates(height: number)}
  {#each cols as { start }, i (start)}
    {#if (cols.length - 1 - i) % every === 0}
      <text x={cx(i)} y={height - 6} text-anchor="middle" class="tick" class:on={hovered === i}>{periodLabel(start, by)}</text>
    {/if}
  {/each}
{/snippet}

{#snippet tooltip()}
  {#if tip}
    <Tooltip bind:width={tipW} x={tipX} y={8} offset={0} title={periodName(tip.start, by)} rows={tipRows(tip)} />
  {/if}
{/snippet}

<div class="history" aria-busy={!co2 && !error} bind:clientWidth={width}>
  <section class="carbon" aria-label="Carbon impact">
    <div class="carbon-summary">
      <div>
        <h3><Hint text="Estimated CO₂ difference versus supplying the same consumption directly from the grid. Consumption includes connected load and battery overhead.">{co2Label(totals.avoided)}</Hint></h3>
        <p class="baseline">Estimated · Baseline: same consumption from grid</p>
        <p class="total" class:avoided={hasReadings && totals.avoided > 0} class:added={totals.avoided < 0}><b>{hasReadings ? fmtMass(Math.abs(totals.avoided)) : "–"}</b><small>kg</small></p>
      </div>
      <dl class="breakdown">
        <div><dt><i class="sw solar"></i>Solar</dt><dd>{hasReadings ? `${signed(totals.solarKg)} kg` : "–"}</dd></div>
        <div><dt><i class="sw shift"></i><Hint text="CO₂ saved by charging at cleaner times. Negative values mean added emissions.">Load shifting</Hint></dt><dd>{hasReadings ? `${signed(totals.shiftKg)} kg` : "–"}</dd></div>
      </dl>
    </div>
    <div class="chart-head">
      <h4>Carbon impact by {by} <span>kg CO₂</span></h4>
      <p>Above zero: avoided <span>·</span> Below: added</p>
    </div>
    <div class="plot" tabindex="0" role="slider" aria-valuemin={0} aria-valuemax={Math.max(0, cols.length - 1)} aria-valuenow={hovered ?? Math.max(0, cols.length - 1)} aria-valuetext={tip ? `${periodName(tip.start, by)}: ${tipRows(tip, "carbon").map((r) => `${r.name} ${r.value ?? ""}`).join(", ")}` : "Select a period"}
      aria-label="Carbon impact chart. Left and right arrow keys select a period; Escape dismisses values."
      onfocus={() => { active = "carbon"; hovered ??= cols.length ? cols.length - 1 : null; }}
      onkeydown={navigate} onblur={() => (hovered = null)}
      onpointermove={(e) => { active = "carbon"; pick(e); }}
      onpointerdown={(e) => { active = "carbon"; pick(e); }}
      onpointerup={(e) => e.pointerType === "touch" && holdTouch(e.currentTarget, () => (hovered = null))}
      onpointerleave={(e) => e.pointerType !== "touch" && (hovered = null)} onpointercancel={() => (hovered = null)}>
      <svg viewBox="0 0 {width} {CH}" height={CH} role="img" aria-label="CO₂ avoided above zero and added below zero per {by}, kg">
        {#each cTicks as v (v)}
          <line x1={M.l} x2={width - M.r} y1={cy(v)} y2={cy(v)} stroke={v ? "var(--rule)" : "var(--ink-3)"} />
          <text x={M.l - 6} y={cy(v) + 4} text-anchor="end" class="tick">{fmtTick(v)}</text>
        {/each}
        {#if hovered != null}<rect class="hl" x={cx(hovered) - gw / 2} y={0} width={gw} height={CH - LABELS} />{/if}
        {#each cols as { start, p }, i (start)}
          {#if p}
            {#each parts(p) as x (x.color)}
              <path d={bar(cx(i) - bw / 2, cy(x.from), cy(x.to))} fill={x.color} />
            {/each}
          {:else}
            <text x={cx(i)} y={cy(0) - 6} text-anchor="middle" class="tick">–<title>No readings</title></text>
          {/if}
        {/each}
        {@render dates(CH)}
      </svg>
      {#if active === "carbon"}{@render tooltip()}{/if}
    </div>
  </section>

  <section class="energy" aria-label="Energy history">
    <div class="energy-summary">
      <div class="metric">
        <h3><Hint text="Solar and grid energy entering the Jackery. Supply and consumption can differ as stored charge changes.">Energy supplied</Hint></h3>
        <p class="total"><b>{hasReadings ? totals.supplied[0] : "–"}</b><small>{totals.supplied[1]}</small></p>
        <dl class="breakdown">
          <div><dt><i class="sw solar"></i>Solar</dt><dd>{hasReadings ? span(totals.solar) : "–"}</dd></div>
          <div><dt><i class="sw grid"></i>Grid</dt><dd>{hasReadings ? span(totals.grid) : "–"}</dd></div>
        </dl>
      </div>
      <div class="metric">
        <h3><Hint text="Energy used by appliances connected to the Jackery, plus battery overhead.">Consumption</Hint></h3>
        <p class="total"><b>{hasReadings ? totals.load[0] : "–"}</b><small>{totals.load[1]}</small></p>
        <dl class="breakdown">
          <div><dt><i class="sw load"></i><Hint text="Appliances connected to the Jackery’s outputs, whether supplied by battery, solar or grid pass-through. Excludes battery overhead.">Connected load</Hint></dt><dd>{hasReadings ? span(totals.appliances) : "–"}</dd></div>
          <div><dt><i class="sw overhead"></i><Hint text="Energy used by the Jackery itself, separate from connected appliances.">Battery overhead</Hint></dt><dd>{hasReadings ? span(totals.overhead) : "–"}</dd></div>
        </dl>
      </div>
    </div>
    <div class="chart-head">
      <h4>Energy by {by} <span>kWh</span></h4>
      <p>Left: supplied <span>·</span> Right: consumed</p>
    </div>
    <div class="plot" tabindex="0" role="slider" aria-valuemin={0} aria-valuemax={Math.max(0, cols.length - 1)} aria-valuenow={hovered ?? Math.max(0, cols.length - 1)} aria-valuetext={tip ? `${periodName(tip.start, by)}: ${tipRows(tip, "energy").map((r) => `${r.name} ${r.value ?? ""}`).join(", ")}` : "Select a period"}
      aria-label="Energy chart. Left and right arrow keys select a period; Escape dismisses values."
      onfocus={() => { active = "energy"; hovered ??= cols.length ? cols.length - 1 : null; }}
      onkeydown={navigate} onblur={() => (hovered = null)}
      onpointermove={(e) => { active = "energy"; pick(e); }}
      onpointerdown={(e) => { active = "energy"; pick(e); }}
      onpointerup={(e) => e.pointerType === "touch" && holdTouch(e.currentTarget, () => (hovered = null))}
      onpointerleave={(e) => e.pointerType !== "touch" && (hovered = null)} onpointercancel={() => (hovered = null)}>
      <svg viewBox="0 0 {width} {EH}" height={EH} role="img" aria-label="Energy supplied and consumed per {by}, kWh">
        {#each eTicks as v (v)}
          <line x1={M.l} x2={width - M.r} y1={ey(v)} y2={ey(v)} stroke={v ? "var(--rule)" : "var(--ink-3)"} />
          <text x={M.l - 6} y={ey(v) + 4} text-anchor="end" class="tick">{fmtTick(v)}</text>
        {/each}
        {#if hovered != null}<rect class="hl" x={cx(hovered) - gw / 2} y={0} width={gw} height={EH - LABELS} />{/if}
        {#each cols as { start, p }, i (start)}
          {#if p}
            {@const left = cx(i) - bw - 2}
            {@const right = cx(i) + 2}
            {@const s = p.solar_wh / 1000}
            {@const g = p.grid_wh / 1000}
            {@const a = (p.load_wh - p.overhead_wh) / 1000}
            <path d={bar(left, ey(0), ey(s))} fill="var(--solar)" />
            <path d={bar(left, ey(s), ey(s + g))} fill="var(--grid)" />
            <path d={bar(right, ey(0), ey(a))} fill="var(--load)" />
            <path d={bar(right, ey(a), ey(p.load_wh / 1000))} fill="var(--overhead)" />
          {:else}
            <text x={cx(i)} y={ey(0) - 6} text-anchor="middle" class="tick">–<title>No readings</title></text>
          {/if}
        {/each}
        {@render dates(EH)}
      </svg>
      {#if active === "energy"}{@render tooltip()}{/if}
    </div>
  </section>


  {#if co2 && cols.some(({ p }) => !p)}<p class="empty">– No readings</p>{/if}
  <details>
    <summary>Period values</summary>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the data table horizontally.) -->
    <div class="table-scroll" tabindex="0" role="region" aria-label="History values">
      <table>
        <caption>Energy in kWh · Carbon impact in kg CO₂ · Negative carbon values mean added emissions</caption>
        <thead><tr><th scope="col">Period</th><th scope="col">Solar</th><th scope="col">Grid</th><th scope="col">Connected load</th><th scope="col">Battery overhead</th><th scope="col">CO₂ avoided</th><th scope="col">From solar</th><th scope="col">From load shifting</th></tr></thead>
        <tbody>
          {#each cols as { start, p } (start)}
            <tr><th scope="row">{periodName(start, by)}</th>
              {#if p}
                <td>{(p.solar_wh / 1000).toFixed(2)}</td><td>{(p.grid_wh / 1000).toFixed(2)}</td><td>{((p.load_wh - p.overhead_wh) / 1000).toFixed(2)}</td><td>{(p.overhead_wh / 1000).toFixed(2)}</td><td>{signed(kg(p.avoided_lb))}</td><td>{signed(kg(p.solar_lb))}</td><td>{signed(kg(p.shift_lb))}</td>
              {:else}<td colspan="7">No readings</td>{/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </details>
  {#if error}<p class="empty" role="alert">{error}</p>
  {:else if !co2}<p class="empty" role="status">Loading history…</p>
  {:else if !hasReadings}<p class="empty" role="status">No readings for this period.</p>{/if}
</div>

<style>
  .history {
    display: grid;
    gap: var(--space-6);
    padding-top: 8px;
  }
  section { min-width: 0; }
  .energy-summary {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 32px;
  }
  .metric + .metric { border-left: 1px solid var(--line); padding-left: 32px; }
  h3 { margin: 0; font: 500 14px var(--f-sans); color: var(--ink-2); }
  .total { margin: 6px 0 14px; }
  .total b { font: 500 var(--text-metric) / 1.15 var(--f-sans); letter-spacing: -0.025em; }
  .total small { margin-left: 5px; font-size: 14px; color: var(--ink-3); }
  .baseline { margin: 5px 0 0; font-size: 12px; color: var(--ink-3); }
  .total.avoided b { color: var(--good-ink); }
  .total.added b { color: var(--bad-ink); }
  .breakdown { display: grid; gap: 6px; margin: 0; max-width: 340px; font-size: 13px; }
  .breakdown > div { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  dt { display: flex; align-items: center; gap: 7px; color: var(--ink-2); }
  dd { margin: 0; white-space: nowrap; }
  .sw { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: var(--radius-key); }
  .solar { background: var(--solar); }
  .grid { background: var(--grid); }
  .load { background: var(--load); }
  .overhead { background: var(--overhead); }
  .shift { background: var(--shift); }
  .energy { border-top: 1px solid var(--line); padding-top: var(--space-6); }
  .carbon-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 32px; align-items: center; }
  .carbon-summary .total { margin-bottom: 0; }
  .chart-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 4px 16px; margin: 20px 0 8px; }
  h4 { margin: 0; font: 500 13px var(--f-sans); color: var(--ink-2); }
  h4 span { margin-left: 6px; font-weight: 400; color: var(--ink-3); }
  .chart-head p { margin: 0; font-size: 12px; color: var(--ink-3); }
  .chart-head p span { margin: 0 4px; }
  .plot { position: relative; touch-action: pan-y; -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; border-radius: var(--radius-surface); }
  .plot:focus-visible, .table-scroll:focus-visible { outline: 2px solid var(--grid); outline-offset: 4px; }
  svg { display: block; width: 100%; }
  .tick { font: var(--text-meta) var(--f-sans); fill: var(--ink-3); }
  .tick.on { fill: var(--ink); }
  .hl { fill: var(--ink); opacity: 0.06; }
  details { font-size: 12px; color: var(--ink-2); }
  summary { cursor: pointer; width: fit-content; padding: 4px 0; }
  .table-scroll { overflow-x: auto; margin-top: 8px; }
  table { border-collapse: collapse; width: 100%; white-space: nowrap; }
  caption { text-align: left; color: var(--ink-3); margin-bottom: 8px; }
  th, td { text-align: right; padding: 8px; border-bottom: 1px solid var(--line); }
  th { font-weight: 500; }
  th:first-child { text-align: left; }
  .empty { margin: 0; color: var(--ink-3); font-size: 13px; }
  @media (max-width: 640px) {
    .energy-summary { grid-template-columns: 1fr; gap: 20px; }
    .metric + .metric { border-left: 0; border-top: 1px solid var(--line); padding: 20px 0 0; }
    .breakdown { max-width: none; }
    .carbon-summary { grid-template-columns: 1fr; gap: 16px; }
    .total b { font-size: var(--text-metric-mobile); }
  }
</style>
