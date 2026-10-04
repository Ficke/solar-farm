<script lang="ts">
  // Energy and CO2 avoided per day, week or month, one column per period
  // across both charts. Hovering a column shows its numbers.
  import type { Co2 } from "./api";
  import { fmtLb, fmtWh, niceTicks, periodLabel, periodName, type Slot, slots } from "./co2";

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
  const bw = $derived(Math.max(4, Math.min(28, gw * 0.6)));
  const cx = (i: number) => M.l + gw * i + gw / 2;
  // Skip period labels when they'd collide; always keep the latest.
  const every = $derived(Math.max(1, Math.ceil((by === "month" ? 36 : 48) / gw)));

  // Energy, kWh: solar and grid stacked above zero (what went in), load below (what came out).
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

  // CO2 avoided, lb: below zero when charging cost more than it saved.
  const cTicks = $derived.by(() => {
    const v = cols.map(({ p }) => p?.avoided_lb ?? 0);
    return niceTicks(Math.min(0, ...v), Math.max(0.05, ...v), 3);
  });
  const cLo = $derived(cTicks[0] ?? 0);
  const cHi = $derived(cTicks.at(-1) ?? 1);
  const cy = (lb: number) => PAD.t + ((cHi - lb) / (cHi - cLo)) * (CH - LABELS - PAD.t - PAD.b);

  const fmtTick = (v: number) => String(+v.toFixed(3));

  const sum = (k: "solar_wh" | "grid_wh" | "load_wh" | "avoided_lb") =>
    cols.reduce((a, { p }) => a + (p?.[k] ?? 0), 0);
  const totals = $derived({
    solar: fmtWh(sum("solar_wh")),
    grid: fmtWh(sum("grid_wh")),
    load: fmtWh(sum("load_wh")),
    avoided: sum("avoided_lb"),
  });

  const tip = $derived<Slot | null>(hovered != null ? (cols[hovered] ?? null) : null);
  // Beside the hovered column, on whichever side has room, kept inside the card.
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

  // A bar from y0 to y1, rounded only at the y1 end so stacked segments meet flat.
  function bar(x: number, y0: number, y1: number, round: boolean) {
    const h = Math.abs(y0 - y1);
    if (h < 0.5) return "";
    const r = round ? Math.min(3, h, bw / 2) : 0;
    const d = y1 < y0 ? r : -r;
    return `M${x},${y0}V${y1 + d}Q${x},${y1} ${x + r},${y1}H${x + bw - r}Q${x + bw},${y1} ${x + bw},${y1 + d}V${y0}Z`;
  }
  const co2Label = (lb: number) => (lb < 0 ? "CO₂ added" : "CO₂ avoided");
  const span = (wh: [string, string]) => `${wh[0]} ${wh[1]}`;
</script>

<dl class="tiles">
  <div>
    <dt><i class="sw" style:background="var(--solar)"></i>Solar</dt>
    <dd><b>{co2 ? totals.solar[0] : "–"}</b><small>{totals.solar[1]}</small></dd>
  </div>
  <div>
    <dt><i class="sw" style:background="var(--grid)"></i>Grid</dt>
    <dd><b>{co2 ? totals.grid[0] : "–"}</b><small>{totals.grid[1]}</small></dd>
  </div>
  <div>
    <dt><i class="sw" style:background="var(--ink-3)"></i>Load</dt>
    <dd><b>{co2 ? totals.load[0] : "–"}</b><small>{totals.load[1]}</small></dd>
  </div>
  <div>
    <dt>
      <i class="sw" style:background={totals.avoided < 0 ? "var(--bad)" : "var(--good)"}></i>{co2Label(totals.avoided)}
    </dt>
    <dd><b>{co2 ? fmtLb(Math.abs(totals.avoided)) : "–"}</b><small>lb</small></dd>
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
  <h3>Energy in and out, kWh</h3>
  <svg viewBox="0 0 {width} {EH}" height={EH} role="img" aria-label="Solar, grid and load energy per {by}">
    {#each eTicks as v (v)}
      <line x1={M.l} x2={width - M.r} y1={ey(v)} y2={ey(v)} stroke={v ? "var(--line)" : "var(--ink-3)"} />
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
        <path d={bar(x, ey(0), ey(s), g === 0)} fill="var(--solar)" />
        <path d={bar(x, ey(s), ey(s + g), true)} fill="var(--grid)" />
        <path d={bar(x, ey(0), ey(-p.load_wh / 1000), true)} fill="var(--ink-3)" />
      {/if}
    {/each}
  </svg>

  <h3>Net CO₂ avoided, lb</h3>
  <svg viewBox="0 0 {width} {CH}" height={CH} role="img" aria-label="CO2 avoided per {by}">
    {#each cTicks as v (v)}
      <line x1={M.l} x2={width - M.r} y1={cy(v)} y2={cy(v)} stroke={v ? "var(--line)" : "var(--ink-3)"} />
      <text x={M.l - 6} y={cy(v) + 4} text-anchor="end" class="tick">{fmtTick(v)}</text>
    {/each}
    {#if hovered != null}
      <rect class="hl" x={cx(hovered) - gw / 2} y={0} width={gw} height={CH - LABELS + 4} />
    {/if}
    {#each cols as { start, p }, i (start)}
      {#if p && p.avoided_lb !== 0}
        {@const top = cy(Math.max(0, p.avoided_lb))}
        <rect
          x={cx(i) - bw / 2}
          y={top}
          width={bw}
          height={Math.max(1, Math.abs(cy(p.avoided_lb) - cy(0)))}
          rx="2"
          fill={p.avoided_lb < 0 ? "var(--bad)" : "var(--good)"}
        />
      {/if}
      {#if (cols.length - 1 - i) % every === 0}
        <text x={cx(i)} y={CH - 6} text-anchor="middle" class="tick" class:on={hovered === i}
          >{periodLabel(start, by)}</text
        >
      {/if}
    {/each}
  </svg>

  {#if tip}
    {@const p = tip.p}
    <div class="tip" bind:clientWidth={tipW} style:left="{tipX}px">
      <div class="when">{periodName(tip.start, by)}</div>
      {#if p}
        <div class="row"><span class="key" style:background="var(--solar)"></span><strong>{span(fmtWh(p.solar_wh))}</strong><span class="name">Solar</span></div>
        <div class="row"><span class="key" style:background="var(--grid)"></span><strong>{span(fmtWh(p.grid_wh))}</strong><span class="name">Grid</span></div>
        <div class="row"><span class="key" style:background="var(--ink-3)"></span><strong>{span(fmtWh(p.load_wh))}</strong><span class="name">Load</span></div>
        <div class="row">
          <span class="key" style:background={p.avoided_lb < 0 ? "var(--bad)" : "var(--good)"}></span>
          <strong>{fmtLb(Math.abs(p.avoided_lb))} lb</strong><span class="name">{co2Label(p.avoided_lb)}</span>
        </div>
      {:else}
        <div class="name">No readings</div>
      {/if}
    </div>
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
    color: var(--ink-3);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  dd {
    margin: 0;
  }
  dd b {
    font: 600 28px var(--f-display);
    font-variant-numeric: tabular-nums;
  }
  dd small {
    font-size: 13px;
    margin-left: 4px;
    color: var(--ink-3);
  }
  .sw {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
  h3 {
    font: 500 12px var(--f-body);
    color: var(--ink-3);
    margin: 14px 0 2px;
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
    font: 11px var(--f-mono);
    fill: var(--ink-3);
  }
  .tick.on {
    fill: var(--ink);
  }
  .hl {
    fill: var(--ink);
    opacity: 0.06;
  }
  .tip {
    position: absolute;
    top: 28px;
    z-index: 2;
    pointer-events: none;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: 0 4px 16px rgb(0 0 0 / 0.15);
    padding: 8px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  .when {
    color: var(--ink-2);
    margin-bottom: 4px;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 6px;
    line-height: 1.6;
  }
  .row strong {
    color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .name {
    color: var(--ink-3);
  }
  .key {
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
</style>
