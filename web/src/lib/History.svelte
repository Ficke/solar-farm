<script lang="ts">
  // Align energy and CO2 columns by period on both charts.
  import type { Co2 } from "./api";
  import { fmtMass, fmtWh, niceTicks, periodLabel, periodName, type Slot, slots } from "./co2";
  import Hint from "./Hint.svelte";
  import Tooltip, { type TipRow } from "./Tooltip.svelte";
  import { kg } from "./units";

  let { co2, now }: { co2: Co2 | undefined; now: number } = $props();
  let width = $state(400);
  let hovered = $state<number | null>(null);
  let tipW = $state(0);

  const by = $derived(co2?.by ?? "day");
  const cols = $derived(co2 ? slots(co2.periods, co2.by, now) : []);
  const M = { l: 44, r: 8 };
  const EH = 180; // energy chart
  const CH = 120; // CO2 chart, with the period labels under it
  const PAD = { t: 8, b: 4 };
  const LABELS = 22;

  const gw = $derived((width - M.l - M.r) / Math.max(cols.length, 1));
  const bw = $derived(Math.max(4, Math.min(20, gw * 0.5)));
  const cx = (i: number) => M.l + gw * i + gw / 2;
  // Skip period labels when they'd collide; always keep the latest.
  const every = $derived(Math.max(1, Math.ceil((by === "month" ? 36 : 48) / gw)));

  // Show input above zero and load below, in kWh.
  const eTicks = $derived(
    niceTicks(
      -Math.max(...cols.map(({ p }) => (p ? p.load_wh / 1000 : 0)), 0),
      Math.max(0.5, ...cols.map(({ p }) => (p ? (p.solar_wh + p.grid_wh) / 1000 : 0))),
      6,
    ),
  );
  const eLo = $derived(eTicks[0] ?? 0);
  const eHi = $derived(eTicks.at(-1) ?? 1);
  const ey = (kwh: number) => PAD.t + ((eHi - kwh) / (eHi - eLo)) * (EH - PAD.t - PAD.b);

  // Stack each source's avoided CO2 up from zero; a negative part (CO2
  // added) stacks down.
  const parts = (p: { solar_lb: number; shift_lb: number }) => {
    let up = 0;
    let down = 0;
    const xs = [
      { lb: kg(p.solar_lb), color: "var(--solar-area)" },
      { lb: kg(p.shift_lb), color: "var(--grid)" },
    ]
      .filter((x) => x.lb !== 0)
      .map((x) => {
        const from = x.lb > 0 ? up : down;
        if (x.lb > 0) up += x.lb;
        else down += x.lb;
        return { ...x, from, to: from + x.lb };
      });
    // Round only the outer end of each stack.
    return xs.map((x) => ({ ...x, outer: x.to === (x.lb > 0 ? up : down) }));
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

  // Round only the outer end so stacked segments meet flush.
  function bar(x: number, y0: number, y1: number, round: boolean) {
    const h = Math.abs(y0 - y1);
    if (h < 0.5) return "";
    const r = round ? Math.min(3, h, bw / 2) : 0;
    const d = y1 < y0 ? r : -r;
    return `M${x},${y0}V${y1 + d}Q${x},${y1} ${x + r},${y1}H${x + bw - r}Q${x + bw},${y1} ${x + bw},${y1 + d}V${y0}Z`;
  }
  const co2Label = (v: number) => (v < 0 ? "CO₂ added" : "CO₂ avoided");
  const signed = (v: number) => (v < 0 ? `−${fmtMass(-v)}` : fmtMass(v));
  const span = (wh: [string, string]) => `${wh[0]} ${wh[1]}`;

  function tipRows({ p }: Slot): TipRow[] {
    if (!p) return [{ name: "No readings" }];
    return [
      { color: "--solar-area", value: span(fmtWh(p.solar_wh)), name: "Solar" },
      { color: "--grid", value: span(fmtWh(p.grid_wh)), name: "Grid" },
      { color: "--load", value: span(fmtWh(p.load_wh - p.overhead_wh)), name: "Load" },
      { color: "--overhead", value: span(fmtWh(p.overhead_wh)), name: "Jackery" },
      {
        value: `${fmtMass(Math.abs(kg(p.avoided_lb)))} kg`,
        name: co2Label(p.avoided_lb),
      },
      { color: "--solar-area", value: `${signed(kg(p.solar_lb))} kg`, name: "From solar" },
      { color: "--grid", value: `${signed(kg(p.shift_lb))} kg`, name: "From load shifting" },
    ];
  }
</script>

<dl class="tiles">
  <div>
    <dt><i class="sw" style:background="var(--solar-area)"></i>Solar</dt>
    <dd><b>{co2 ? totals.solar[0] : "–"}</b><small>{totals.solar[1]}</small></dd>
  </div>
  <div>
    <dt><i class="sw" style:background="var(--grid)"></i>Grid</dt>
    <dd><b>{co2 ? totals.grid[0] : "–"}</b><small>{totals.grid[1]}</small></dd>
  </div>
  <div>
    <dt><i class="sw" style:background="var(--load)"></i>Load</dt>
    <dd><b>{co2 ? totals.load[0] : "–"}</b><small>{totals.load[1]}</small></dd>
    {#if co2}
      <dd class="split">Appliances {span(totals.appliances)} · Jackery {span(totals.overhead)}</dd>
    {/if}
  </div>
  <div>
    <dt>
      <Hint
        text="CO₂ the same load would have caused on the grid at the time it ran, minus CO₂ of the energy that ran it. Solar: solar energy used, directly or from the battery. Load shifting: grid energy stored at cleaner times, net of charging losses; negative when it was dirtier."
        >{co2Label(totals.avoided)}</Hint
      >
    </dt>
    <dd><b>{co2 ? fmtMass(Math.abs(totals.avoided)) : "–"}</b><small>kg</small></dd>
    {#if co2}
      <dd class="split">Solar {fmtMass(totals.solarKg)} · Shifting {signed(totals.shiftKg)}</dd>
    {/if}
  </div>
</dl>

<div
  class="plot"
  bind:clientWidth={width}
  onpointermove={pick}
  onpointerdown={pick}
  onpointerleave={() => (hovered = null)}
  role="presentation"
>
  <h3 class="legend">
    Energy in and out, kWh
    <span><i class="sw" style:background="var(--load)"></i>Load</span>
    <span><i class="sw" style:background="var(--overhead)"></i>Jackery</span>
  </h3>
  <svg viewBox="0 0 {width} {EH}" height={EH} role="img" aria-label="Solar, grid, load and Jackery energy per {by}">
    {#each eTicks as v (v)}
      <line x1={M.l} x2={width - M.r} y1={ey(v)} y2={ey(v)} stroke={v ? "var(--rule)" : "var(--ink-3)"} />
      <text x={M.l - 6} y={ey(v) + 4} text-anchor="end" class="tick">{fmtTick(Math.abs(v))}</text>
    {/each}
    {#if hovered != null}
      <rect class="hl" x={cx(hovered) - gw / 2} y={0} width={gw} height={EH} />
    {/if}
    {#each cols as { start, p }, i (start)}
      {#if p}
        {@const x = cx(i) - bw / 2}
        {@const s = p.solar_wh / 1000}
        {@const g = p.grid_wh / 1000}
        <path d={bar(x, ey(0), ey(s), g === 0)} fill="var(--solar-area)" />
        <path d={bar(x, s > 0 ? ey(s) - 2 : ey(s), ey(s + g), true)} fill="var(--grid)" />
        {@const a = (p.load_wh - p.overhead_wh) / 1000}
        <path d={bar(x, ey(0) + 1, ey(-a), p.overhead_wh === 0)} fill="var(--load)" />
        <path d={bar(x, a > 0 ? ey(-a) + 2 : ey(-a) + 1, ey(-p.load_wh / 1000), true)} fill="var(--overhead)" />
      {/if}
    {/each}
  </svg>

  <h3 class="legend">
    CO₂ avoided, kg
    <span><i class="sw" style:background="var(--solar-area)"></i>Solar</span>
    <span><i class="sw" style:background="var(--grid)"></i>Load shifting</span>
  </h3>
  <svg viewBox="0 0 {width} {CH}" height={CH} role="img" aria-label="CO2 avoided per {by}">
    {#each cTicks as v (v)}
      <line x1={M.l} x2={width - M.r} y1={cy(v)} y2={cy(v)} stroke={v ? "var(--rule)" : "var(--ink-3)"} />
      <text x={M.l - 6} y={cy(v) + 4} text-anchor="end" class="tick">{fmtTick(v)}</text>
    {/each}
    {#if hovered != null}
      <rect class="hl" x={cx(hovered) - gw / 2} y={0} width={gw} height={CH - LABELS + 4} />
    {/if}
    {#each cols as { start, p }, i (start)}
      {#if p}
        {#each parts(p) as x (x.color)}
          {@const gap = x.from === 0 ? 0 : x.lb > 0 ? -1 : 1}
          <path d={bar(cx(i) - bw / 2, cy(x.from) + gap, cy(x.to), x.outer)} fill={x.color} />
        {/each}
      {/if}
      {#if (cols.length - 1 - i) % every === 0}
        <text x={cx(i)} y={CH - 6} text-anchor="middle" class="tick" class:on={hovered === i}
          >{periodLabel(start, by)}</text
        >
      {/if}
    {/each}
  </svg>

  {#if tip}
    <Tooltip
      bind:width={tipW}
      x={tipX}
      y={28}
      offset={0}
      title={periodName(tip.start, by)}
      rows={tipRows(tip)}
    />
  {/if}
</div>

<style>
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 12px 16px;
    margin: 0 0 4px;
  }
  dt {
    font-size: 13px;
    font-weight: 500;
    color: var(--ink-2);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  dd {
    margin: 0;
  }
  dd b {
    font: 500 28px / 1.2 var(--f-sans);
    letter-spacing: -0.02em;
  }
  dd small {
    font-size: 13px;
    margin-left: 4px;
    color: var(--ink-3);
  }
  .split {
    font-size: 13px;
    color: var(--ink-3);
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 12px;
  }
  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-weight: 400;
    color: var(--ink-3);
  }
  .sw {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
  h3 {
    font: 500 13px var(--f-sans);
    color: var(--ink-2);
    margin: 24px 0 4px;
  }
  .plot {
    position: relative;
    touch-action: pan-y;
  }
  svg {
    display: block;
    width: 100%;
  }
  .tick {
    font: 11px var(--f-sans);
    fill: var(--ink-3);
  }
  .tick.on {
    fill: var(--ink);
  }
  .hl {
    fill: var(--ink);
    opacity: 0.06;
  }
</style>
