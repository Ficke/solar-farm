<script lang="ts">
  import { onMount } from "svelte";
  import { align } from "./lib/align";
  import { type Accuracy, api, type Co2, type Now, type Period, type Timeline } from "./lib/api";
  import { COUNTS } from "./lib/co2";
  import History from "./lib/History.svelte";
  import { FUTURE, PAST } from "./lib/layout";
  import { GROUPS, stackMix } from "./lib/mix";
  import PlanView from "./lib/PlanView.svelte";
  import Segmented from "./lib/Segmented.svelte";
  import { explain } from "./lib/status";
  import TimeChart from "./lib/TimeChart.svelte";
  import { type Mode, setMode, theme } from "./lib/theme.svelte";
  import { ago, fmtWhen, hours } from "./lib/time";

  const MODES: { value: Mode; label: string }[] = [
    { value: "system", label: "Auto" },
    { value: "light", label: "Light" },
    { value: "dark", label: "Dark" },
  ];
  const LEADS = [1, 3, 6, 12].map((h) => ({ value: h, label: `${h} h` }));
  // Marginal CO2 is colored by its value, so clean hours read at a glance.
  const CO2_RAMP: [number, string][] = [
    [250, "--co2-clean"],
    [550, "--co2-mid"],
    [850, "--co2-dirty"],
  ];
  const PERIODS = (Object.keys(COUNTS) as Period[]).map((p) => ({
    value: p,
    label: p[0].toUpperCase() + p.slice(1),
  }));

  let now = $state<Now>();
  let tl = $state<Timeline>();
  let acc = $state<Accuracy>();
  let lead = $state(6);
  let co2 = $state<Co2>();
  let by = $state<Period>("day");
  let error = $state("");
  let clock = $state(Date.now() / 1000);

  // The lead and period toggles fetch their own data. A response only lands
  // if its toggle still shows the value it was asked for, so a slow answer
  // can't overwrite a newer pick.
  const fetchAccuracy = (h: number) =>
    api.accuracy(h).then((v) => {
      if (lead === h) acc = v;
    });
  const fetchCo2 = (p: Period) =>
    api.co2(p, COUNTS[p]).then((v) => {
      if (by === p) co2 = v;
    });

  async function run(jobs: Promise<unknown>[]) {
    try {
      await Promise.all(jobs);
      error = "";
      tick();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  /** Readings every 30 s, the timeline every minute, everything else every 15 minutes. */
  function load(what: "now" | "charts" | "all") {
    const jobs: Promise<unknown>[] = [api.now().then((v) => (now = v))];
    if (what !== "now") jobs.push(api.timeline(24).then((v) => (tl = v)));
    if (what === "all") jobs.push(fetchAccuracy(lead), fetchCo2(by));
    return run(jobs);
  }

  function pickLead(h: number) {
    lead = h;
    run([fetchAccuracy(h)]);
  }

  function pickPeriod(p: Period) {
    by = p;
    run([fetchCo2(p)]);
  }

  const tick = () => (clock = Date.now() / 1000);

  onMount(() => {
    load("all");
    // One 30 s beat drives every refresh, so no request is ever sent twice
    // at once. Hidden tabs skip beats and catch up when shown again.
    let beat = 0;
    const visible = () => document.visibilityState === "visible";
    const timers = [
      setInterval(() => {
        if (!visible()) return;
        beat++;
        load(beat % 30 === 0 ? "all" : beat % 2 === 0 ? "charts" : "now");
      }, 30_000),
      setInterval(tick, 1_000),
    ];
    const wake = () => {
      tick();
      if (!visible()) return;
      beat = 0;
      load("all");
    };
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
    <h1><i class="mark" aria-hidden="true"></i>Solar Farm</h1>
    <div class="tools">
      {#if stale.length}
        <p class="sub">
          <span class="dot bad"></span>No data from {stale.map((h) => h.name.toLowerCase()).join(", ")}
        </p>
      {/if}
      <Segmented label="Theme" options={MODES} value={theme.mode} onpick={setMode} />
    </div>
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
        <dd class="gauge" aria-hidden="true">
          <i style:width="{s?.battery_pct ?? 0}%"></i>
        </dd>
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
      <p class="n">Fallback schedule · no battery data</p>
    {/if}
    <PlanView {windows} {forecast} {from} {to} now={tnow} />
  </section>

  <section class="card charts" aria-labelledby="grid-h">
    <h2 id="grid-h">Grid</h2>
    <div class="head">
      <h3>CO₂, lb/MWh</h3>
      <div class="ctl">
        <span class="stat">Forecast error</span>
        <Segmented label="Hours ahead" options={LEADS} value={lead} onpick={pickLead} />
        <span class="stat"><b>{acc?.error ?? "–"}</b> lb/MWh</span>
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
        { label: "Marginal", color: "--co2-mid", ramp: CO2_RAMP, unit: "lb/MWh" },
        {
          label: "Forecast",
          color: "--co2-mid",
          ramp: CO2_RAMP,
          dash: [4, 4],
          width: 1.5,
          unit: "lb/MWh",
        },
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
      series={[{ label: "Battery", color: "--battery", unit: "%" }]}
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
        { label: "Load", color: "--ink-3", width: 1.5, unit: "W" },
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
      <Segmented label="Period" options={PERIODS} value={by} onpick={pickPeriod} />
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
    gap: 40px;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: -16px;
  }
  h1 {
    display: flex;
    align-items: center;
    gap: 8px;
    font: 600 15px var(--f-sans);
    letter-spacing: -0.005em;
    margin: 0;
  }
  .mark {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--solar);
  }
  h2 {
    font: 600 15px var(--f-sans);
    letter-spacing: -0.005em;
    margin: 0 0 10px;
  }
  .tools {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  .sub {
    margin: 0;
    font-size: 13px;
    color: var(--bad-ink);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .sub .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
  .dot.bad {
    background: var(--bad);
  }
  .banner {
    margin: 0;
    padding: 10px 14px;
    border-radius: 6px;
    background: var(--bad-bg);
    color: var(--bad-ink);
    font-size: 14px;
  }
  .card {
    border-top: 1px solid var(--line);
    padding-top: 16px;
    min-width: 0;
  }
  .card.now {
    border-top: 0;
    padding-top: 0;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px 12px;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }
  .head h2 {
    margin: 0;
  }
  h3 {
    font: 500 13px var(--f-sans);
    color: var(--ink-2);
    margin: 24px 0 4px;
  }
  .charts h2 + h3 {
    margin-top: 4px;
  }
  .ctl {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .stat {
    font-size: 13px;
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
    align-items: baseline;
  }
  .headline h2 {
    font-size: 30px;
    font-weight: 600;
    letter-spacing: -0.02em;
    line-height: 1.2;
    margin: 0;
  }
  .headline p {
    margin: 4px 0 0;
    color: var(--ink-2);
  }
  .state {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid var(--ink-3);
    flex: none;
    transform: translateY(-3px);
  }
  .now.on .state {
    border-color: var(--grid);
    background: var(--grid);
    box-shadow: 0 0 0 4px var(--grid-fill);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    margin: 28px 0 0;
  }
  .tiles > div {
    padding: 2px 20px;
    border-left: 1px solid var(--line);
  }
  .tiles > div:first-child {
    padding-left: 0;
    border-left: 0;
  }
  @media (max-width: 640px) {
    .tiles {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      row-gap: 20px;
    }
    .tiles > div:nth-child(3) {
      padding-left: 0;
      border-left: 0;
    }
    .headline h2 {
      font-size: 24px;
    }
  }
  dt {
    font-size: 13px;
    font-weight: 500;
    color: var(--ink-2);
  }
  dd {
    margin: 0;
  }
  dd b {
    font: 500 36px / 1.15 var(--f-sans);
    letter-spacing: -0.025em;
  }
  dd small {
    font-size: 14px;
    margin-left: 3px;
    color: var(--ink-3);
  }
  .gauge {
    height: 4px;
    margin: 8px 0 2px;
    border-radius: 2px;
    background: var(--panel-2);
    overflow: hidden;
  }
  .gauge i {
    display: block;
    height: 100%;
    background: var(--ink);
    border-radius: 2px;
  }
  .n {
    font-size: 13px;
    color: var(--ink-3);
  }
  .key {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 16px;
    margin: 10px 0 0;
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
    box-shadow: inset 0 -2px 0 var(--grid);
  }
  .sw.peak {
    background: repeating-linear-gradient(-45deg, var(--peak-hatch) 0 1.5px, transparent 1.5px 4px);
    box-shadow: inset 0 0 0 1px var(--peak-hatch);
  }
  footer {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 12px;
    color: var(--ink-3);
    border-top: 1px solid var(--line);
    padding-top: 12px;
    margin-top: -16px;
  }
  footer i {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--good);
    margin: 0 6px 1px 0;
  }
  footer .stale {
    color: var(--bad-ink);
  }
  footer .stale i {
    background: var(--bad);
  }
</style>
