<script lang="ts">
  import { onMount } from "svelte";
  import { align } from "./lib/align";
  import { type Accuracy, api, type Co2, type Now, type Period, type Timeline } from "./lib/api";
  import { COUNTS } from "./lib/co2";
  import History from "./lib/History.svelte";
  import { FUTURE, PAST } from "./lib/layout";
  import { GROUPS, stackMix } from "./lib/mix";
  import PlanView from "./lib/PlanView.svelte";
  import { explain } from "./lib/status";
  import TimeChart from "./lib/TimeChart.svelte";
  import { ago, fmtWhen, hours } from "./lib/time";

  const LEADS = [1, 3, 6, 12];

  let now = $state<Now>();
  let tl = $state<Timeline>();
  let acc = $state<Accuracy>();
  let lead = $state(6);
  let co2 = $state<Co2>();
  let by = $state<Period>("day");
  let error = $state("");
  let loadedAt = $state(0);
  let clock = $state(Date.now() / 1000);

  async function load(what: "now" | "charts" | "all") {
    try {
      const jobs: Promise<unknown>[] = [api.now().then((v) => (now = v))];
      if (what !== "now") jobs.push(api.timeline(24).then((v) => (tl = v)));
      if (what === "all") {
        jobs.push(api.accuracy(lead).then((v) => (acc = v)));
        jobs.push(api.co2(by, COUNTS[by]).then((v) => (co2 = v)));
      }
      await Promise.all(jobs);
      error = "";
      loadedAt = Date.now() / 1000;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  async function pickLead(h: number) {
    lead = h;
    acc = await api.accuracy(h);
  }

  async function pickPeriod(p: Period) {
    by = p;
    co2 = await api.co2(p, COUNTS[p]);
  }

  onMount(() => {
    load("all");
    // Hidden tabs don't poll; they catch up when shown again.
    const visible = () => document.visibilityState === "visible";
    const timers = [
      setInterval(() => visible() && load("now"), 30_000),
      // Readings arrive every minute. CO2 and energy totals change slowly and
      // read many documents, so they refresh less often.
      setInterval(() => visible() && load("charts"), 60_000),
      setInterval(() => visible() && load("all"), 15 * 60_000),
      setInterval(() => (clock = Date.now() / 1000), 5_000),
    ];
    const wake = () => visible() && load("all");
    document.addEventListener("visibilitychange", wake);
    return () => {
      timers.forEach(clearInterval);
      document.removeEventListener("visibilitychange", wake);
    };
  });

  const s = $derived(now?.sample ?? null);
  const plug = $derived(now?.plug ?? null);
  const windows = $derived(now?.plan?.windows ?? tl?.windows ?? []);
  const forecast = $derived(tl?.forecast ?? []);
  const tnow = $derived(now?.now ?? clock);
  // One time axis for every chart and the plan strip.
  const base = $derived(tl?.now ?? clock);
  const from = $derived(base - PAST);
  const to = $derived(base + FUTURE);
  const age = (t?: number | null) => (t ? clock - t : Infinity);

  const headline = $derived.by(() => {
    if (!plug) return { title: "No report from the plug yet", detail: "" };
    const why = explain(plug);
    const current = windows.find(([st, e]) => st <= tnow && tnow < e);
    if (plug.on) {
      return {
        title: current ? `Grid on until ${fmtWhen(current[1], tnow)}` : "Grid on",
        detail: why,
      };
    }
    const n = windows.find(([st]) => st > tnow);
    return {
      title: n ? `Grid off until ${fmtWhen(n[0], tnow)}` : "Grid off",
      detail: n ? `${why} · then on for ${hours(n[1] - n[0])}` : why,
    };
  });

  const emissionsData = $derived(
    align([
      (tl?.samples ?? []).map((p) => [p.moer_t ?? p.t, p.moer]),
      [
        ...(acc?.points ?? []).map(([t, , f]) => [t, f] as [number, number | null]),
        ...forecast.map(([t, v]) => [t, v] as [number, number]),
      ],
    ]),
  );
  const mix = $derived(stackMix(tl?.mix ?? []));
  const batteryData = $derived(align([(tl?.samples ?? []).map((p) => [p.t, p.battery_pct])]));
  const powerData = $derived(
    align([
      (tl?.samples ?? []).map((p) => [p.t, p.solar_w]),
      (tl?.plug ?? []).map((p) => [p.t, p.w ?? (p.on ? null : 0)]),
      (tl?.samples ?? []).map((p) => [p.t, p.output_w]),
    ]),
  );

  const health = $derived([
    { name: "Battery", t: s?.t, limit: 900 },
    { name: "Plug", t: plug?.t, limit: 300 },
    { name: "Plan", t: now?.plan?.generated_at, limit: 3 * 3600 },
  ]);
  const stale = $derived(health.filter((h) => age(h.t) > h.limit));
</script>

<main>
  <header>
    <h1>Solar Farm</h1>
    <p class="sub">
      {#if stale.length}
        <span class="dot bad"></span>No data from {stale.map((h) => h.name.toLowerCase()).join(", ")}
      {:else if loadedAt}
        <span class="dot ok"></span>Updated {ago(clock - loadedAt)}
      {/if}
    </p>
  </header>

  {#if error}
    <p class="banner">Couldn't refresh: {error}</p>
  {/if}

  <section class="card now" class:on={plug?.on} aria-labelledby="now-h">
    <div class="headline">
      <span class="state" aria-hidden="true"></span>
      <div>
        <h2 id="now-h">{headline.title}</h2>
        {#if headline.detail}<p>{headline.detail}</p>{/if}
      </div>
    </div>
    <dl class="tiles">
      <div>
        <dt>Battery</dt>
        <dd><b>{s?.battery_pct ?? "–"}</b><small>%</small></dd>
      </div>
      <div>
        <dt>Solar</dt>
        <dd><b>{s?.solar_w ?? "–"}</b><small>W</small></dd>
        <dd class="n">{now ? `${now.today.solar_wh} Wh today` : ""}</dd>
      </div>
      <div>
        <dt>Grid</dt>
        <dd><b>{plug?.w != null ? Math.round(plug.w) : "–"}</b><small>W</small></dd>
        <dd class="n">{now ? `${now.today.grid_wh} Wh today` : ""}</dd>
      </div>
      <div>
        <dt>Marginal CO₂</dt>
        <dd><b>{s?.moer != null ? Math.round(s.moer) : "–"}</b><small>lb/MWh</small></dd>
        <dd class="n">
          {s?.index != null ? `Cleaner than ${Math.round(100 - s.index)}% of the past month` : ""}
        </dd>
      </div>
    </dl>
  </section>

  <section class="card" aria-labelledby="plan-h">
    <h2 id="plan-h">Plan</h2>
    {#if now?.plan?.strategy === "adaptive"}
      <p class="n">
        {now.plan.grid_wh} Wh from the grid · full by 4 pm · solar {now.plan.solar_day_wh} Wh/day
        ({now.plan.solar_days ? `${now.plan.solar_days}-day average` : "estimate"})
      </p>
      {#if now.plan.shortfall_wh}
        <p class="n">{now.plan.shortfall_wh} Wh short of full by 4 pm</p>
      {/if}
    {:else if now?.plan?.strategy === "fallback"}
      <p class="n">Battery telemetry unavailable or stale. Using a fixed-duration grid fallback.</p>
    {/if}
    <PlanView {windows} {forecast} {from} {to} now={tnow} />
  </section>

  <section class="card charts" aria-labelledby="grid-h">
    <h2 id="grid-h">Grid</h2>
    <div class="head">
      <h3>CO₂, lb/MWh</h3>
      <div class="ctl">
        <span class="stat">
          {#if acc?.error != null}Average error <b>{acc.error}</b>, forecast made{:else}No past forecasts yet, made{/if}
        </span>
        <div class="seg" role="group" aria-label="Hours ahead">
          {#each LEADS as h (h)}
            <button aria-pressed={lead === h} onclick={() => pickLead(h)}>{h} h</button>
          {/each}
        </div>
        <span class="stat">ahead</span>
      </div>
    </div>
    <TimeChart
      label="Marginal CO2, past 24 hours and forecast"
      data={emissionsData}
      {from}
      {to}
      now={tnow}
      {windows}
      height={180}
      series={[
        { label: "Marginal", color: "--ink", unit: "lb/MWh" },
        { label: "Forecast", color: "--accent", dash: [5, 4], unit: "lb/MWh" },
      ]}
    />
    <h3>Generation by source, GW</h3>
    <TimeChart
      label="CAISO generation by source, past 24 hours"
      data={mix.stacked}
      tipData={mix.raw}
      shade={false}
      {from}
      {to}
      now={tnow}
      height={160}
      series={GROUPS.map((g) => ({
        label: g.label,
        color: g.color,
        fill: g.color,
        area: true,
        width: 1,
        unit: "GW",
        digits: 1,
      }))}
    />
  </section>

  <section class="card charts" aria-labelledby="bat-h">
    <h2 id="bat-h">Battery</h2>
    <h3>Charge, %</h3>
    <TimeChart
      label="Battery charge, past 24 hours"
      data={batteryData}
      {from}
      {to}
      now={tnow}
      {windows}
      height={110}
      yMax={100}
      yRule={now?.plan?.target_pct != null ? { value: now.plan.target_pct, label: `Grid target ${now.plan.target_pct}%` } : undefined}
      series={[{ label: "Battery", color: "--accent", unit: "%" }]}
    />
    <h3>Power, W</h3>
    <TimeChart
      label="Solar and grid power in and load out, past 24 hours"
      data={powerData}
      {from}
      {to}
      now={tnow}
      {windows}
      height={110}
      series={[
        { label: "Solar", color: "--solar", fill: "--solar-fill", unit: "W" },
        { label: "Grid", color: "--grid", fill: "--grid-fill", unit: "W" },
        { label: "Load", color: "--ink-2", width: 1.5, unit: "W" },
      ]}
    />
    <p class="key">
      <span><i class="sw plan"></i>Planned grid charging</span>
      <span><i class="sw peak"></i>Peak, 4–9 PM</span>
    </p>
  </section>

  <section class="card" aria-labelledby="hist-h">
    <div class="head">
      <h2 id="hist-h">Last {COUNTS[by]} {by}s</h2>
      <div class="seg" role="group" aria-label="Period">
        {#each Object.keys(COUNTS) as Period[] as p (p)}
          <button aria-pressed={by === p} onclick={() => pickPeriod(p)}
            >{p[0].toUpperCase() + p.slice(1)}</button
          >
        {/each}
      </div>
    </div>
    <History co2={co2?.by === by ? co2 : undefined} now={tnow} />
  </section>

  <footer>
    {#each health as h (h.name)}
      <span class:stale={age(h.t) > h.limit}><i></i>{h.name} {h.t ? ago(age(h.t)) : "never"}</span>
    {/each}
  </footer>
</main>

<style>
  main {
    max-width: 1080px;
    margin: 0 auto;
    display: grid;
    gap: 16px;
  }
  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
  }
  h1 {
    font: 600 24px var(--f-display);
    margin: 0;
  }
  h2 {
    font: 600 16px var(--f-display);
    margin: 0 0 8px;
  }
  .sub {
    margin: 0;
    font-size: 13px;
    color: var(--ink-3);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .sub .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .dot.ok {
    background: var(--good);
  }
  .dot.bad {
    background: var(--bad);
  }
  .banner {
    margin: 0;
    padding: 10px 14px;
    border-radius: 8px;
    background: var(--bad-bg);
    color: var(--bad);
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 16px 18px;
    min-width: 0;
  }
  .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px 12px;
    flex-wrap: wrap;
    margin-bottom: 8px;
  }
  .head h2 {
    margin: 0;
  }
  h3 {
    font: 500 12px var(--f-body);
    color: var(--ink-3);
    margin: 14px 0 2px;
  }
  .charts h2 + h3 {
    margin-top: 4px;
  }
  .ctl {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .stat {
    font-size: 12px;
    color: var(--ink-3);
  }
  .stat b {
    color: var(--ink);
    font-weight: 600;
  }
  .head h3 {
    margin: 0;
  }
  .headline {
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }
  .headline h2 {
    font-size: 20px;
    margin: 0;
  }
  .headline p {
    margin: 2px 0 0;
    color: var(--ink-2);
  }
  .state {
    width: 14px;
    height: 14px;
    margin-top: 6px;
    border-radius: 50%;
    background: var(--ink-3);
    flex: none;
  }
  .now.on .state {
    background: var(--grid);
    box-shadow: 0 0 0 4px var(--grid-fill);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px;
    margin: 16px 0 0;
    padding-top: 14px;
    border-top: 1px solid var(--line);
  }
  dt {
    font-size: 13px;
    color: var(--ink-3);
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
  .n {
    font-size: 13px;
    color: var(--ink-2);
  }
  .seg {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 8px;
    overflow: hidden;
  }
  .seg button {
    font: inherit;
    font-size: 12px;
    padding: 4px 10px;
    border: 0;
    background: transparent;
    color: var(--ink-2);
    cursor: pointer;
  }
  .seg button + button {
    border-left: 1px solid var(--line);
  }
  .seg button[aria-pressed="true"] {
    background: var(--panel-2);
    color: var(--ink);
    font-weight: 600;
  }
    .key {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    margin: 8px 0 0;
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
  .sw.plan {
    background: var(--plan-band);
    outline: 1px solid var(--grid);
    outline-offset: -1px;
  }
  .sw.peak {
    background: var(--peak-band);
    outline: 1px solid var(--peak-ink);
    outline-offset: -1px;
  }
  footer {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 12px;
    color: var(--ink-3);
  }
  footer i {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--good);
    margin-right: 6px;
  }
  footer .stale {
    color: var(--bad);
  }
  footer .stale i {
    background: var(--bad);
  }
</style>
