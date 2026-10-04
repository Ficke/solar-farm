<script lang="ts">
  import { onMount } from "svelte";
  import { align } from "./lib/align";
  import { type Accuracy, api, type Daily, type Now, type Timeline } from "./lib/api";
  import { FUTURE, PAST } from "./lib/layout";
  import { GROUPS, stackMix } from "./lib/mix";
  import PlanView from "./lib/PlanView.svelte";
  import { explain } from "./lib/status";
  import TimeChart from "./lib/TimeChart.svelte";
  import { ago, fmtWhen, hours } from "./lib/time";
  import WeekBars from "./lib/WeekBars.svelte";

  const RESERVE = 80; // set by hand in the Jackery app
  const LEADS = [1, 3, 6, 12];

  let now = $state<Now>();
  let tl = $state<Timeline>();
  let daily = $state<Daily>();
  let acc = $state<Accuracy>();
  let lead = $state(6);
  let error = $state("");
  let loadedAt = $state(0);
  let clock = $state(Date.now() / 1000);
  let weekTable = $state(false);

  async function load(what: "now" | "all") {
    try {
      const jobs: Promise<unknown>[] = [api.now().then((v) => (now = v))];
      if (what === "all") {
        jobs.push(api.timeline(24).then((v) => (tl = v)));
        jobs.push(api.daily(14).then((v) => (daily = v)));
        jobs.push(api.accuracy(lead).then((v) => (acc = v)));
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

  onMount(() => {
    load("all");
    // Hidden tabs don't poll; they catch up when shown again.
    const visible = () => document.visibilityState === "visible";
    const timers = [
      setInterval(() => visible() && load("now"), 30_000),
      setInterval(() => visible() && load("all"), 5 * 60_000),
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
  const windows = $derived(tl?.windows ?? now?.plan?.windows ?? []);
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
      yRule={{ value: RESERVE, label: `Reserve ${RESERVE}%` }}
      series={[{ label: "Battery", color: "--accent", unit: "%" }]}
    />
    <h3>Power in, W</h3>
    <TimeChart
      label="Solar and grid power into the battery, past 24 hours"
      data={powerData}
      {from}
      {to}
      now={tnow}
      {windows}
      height={110}
      series={[
        { label: "Solar", color: "--solar", fill: "--solar-fill", unit: "W" },
        { label: "Grid", color: "--grid", fill: "--grid-fill", unit: "W" },
      ]}
    />
    <p class="key">
      <span><i class="sw plan"></i>Planned grid charging</span>
      <span><i class="sw peak"></i>Peak, 4–9 PM</span>
    </p>
  </section>

  <div class="row">
    <section class="card" aria-labelledby="week-h">
      <div class="head">
        <h2 id="week-h">Last 7 days</h2>
        <button class="link" onclick={() => (weekTable = !weekTable)}>
          {weekTable ? "Chart" : "Table"}
        </button>
      </div>
      {#if weekTable}
        <table>
          <thead><tr><th>Day</th><th>Solar</th><th>Grid</th><th>Battery peak</th></tr></thead>
          <tbody>
            {#each (daily?.days ?? []).slice(-7) as d (d.day)}
              <tr>
                <td>{d.day}</td>
                <td>{d.solar_wh} Wh</td>
                <td>{d.grid_wh} Wh</td>
                <td>{d.battery_peak_pct ?? "–"}%</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="key">
          <span><i class="sw solar"></i>Solar</span>
          <span><i class="sw grid"></i>Grid</span>
        </p>
        <WeekBars days={daily?.days ?? []} />
      {/if}
    </section>
    <section class="card" aria-labelledby="res-h">
      <h2 id="res-h">Reserve</h2>
      <dl class="pair">
        <div><dt>Set</dt><dd>{RESERVE}%</dd></div>
        <div>
          <dt>Suggested</dt>
          <dd>{daily?.reserve.reserve_pct != null ? `${daily.reserve.reserve_pct}%` : "–"}</dd>
        </div>
      </dl>
      {#if daily?.reserve.reserve_pct != null}
        <p class="n">Room for a {daily.reserve.good_day_wh} Wh solar day</p>
      {/if}
    </section>
  </div>

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
  .pair {
    display: flex;
    gap: 28px;
    margin: 0 0 6px;
  }
  .pair dd {
    margin: 0;
    font: 600 28px var(--f-display);
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
  .link {
    font: inherit;
    font-size: 13px;
    border: 0;
    background: none;
    color: var(--accent);
    cursor: pointer;
    padding: 0;
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
  .sw.solar {
    background: var(--solar);
  }
  .sw.grid {
    background: var(--grid);
  }
  .row {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 16px;
  }
  @media (max-width: 720px) {
    .row {
      grid-template-columns: 1fr;
    }
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
    padding: 6px 8px 6px 0;
    border-top: 1px solid var(--line);
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
