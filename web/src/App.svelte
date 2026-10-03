<script lang="ts">
  import { onMount } from "svelte";
  import { align } from "./lib/align";
  import { type Accuracy, api, type Daily, type Now, type Timeline } from "./lib/api";
  import PlanView from "./lib/PlanView.svelte";
  import { explain } from "./lib/status";
  import TimeChart from "./lib/TimeChart.svelte";
  import { ago, fmtWhen, hours } from "./lib/time";
  import WeekBars from "./lib/WeekBars.svelte";

  const RESERVE = 80; // set by hand in the Jackery app
  const FUTURE = 24 * 3600;
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
    const timers = [
      setInterval(() => load("now"), 30_000),
      setInterval(() => load("all"), 5 * 60_000),
      setInterval(() => (clock = Date.now() / 1000), 5_000),
    ];
    const wake = () => document.visibilityState === "visible" && load("all");
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
  const t0 = $derived(tl?.since ?? clock - 24 * 3600);
  const t1 = $derived((tl?.now ?? clock) + FUTURE);
  const age = (t?: number | null) => (t ? clock - t : Infinity);

  // The one sentence that answers "what is it doing, and what's next?"
  const nextWindow = $derived(windows.find(([, e]) => e > tnow) ?? null);
  const headline = $derived.by(() => {
    if (!plug) return { title: "Waiting for the plug", detail: "It reports every minute." };
    const why = explain(plug, windows, tnow);
    const current = windows.find(([st, e]) => st <= tnow && tnow < e);
    if (plug.on) {
      return {
        title: current ? `Grid on until ${fmtWhen(current[1], tnow)}` : "Grid on",
        detail: why,
      };
    }
    const n = nextWindow && nextWindow[0] > tnow ? nextWindow : null;
    return {
      title: n ? `Grid off · next on ${fmtWhen(n[0], tnow)} for ${hours(n[1] - n[0])}` : "Grid off",
      detail: why,
    };
  });

  const emissionsData = $derived(
    align(
      (tl?.samples ?? []).map((p) => [p.moer_t ?? p.t, p.moer]),
      forecast.map(([t, v]) => [t, v]),
      (tl?.samples ?? []).map((p) => [p.moer_t ?? p.t, p.aoer]),
    ),
  );
  const accuracyData = $derived(
    align(
      (acc?.points ?? []).map(([t, a]) => [t, a]),
      (acc?.points ?? []).map(([t, , f]) => [t, f]),
    ),
  );
  const accFrom = $derived(acc?.points[0]?.[0] ?? tnow - 24 * 3600);
  const batteryData = $derived(align((tl?.samples ?? []).map((p) => [p.t, p.battery_pct])));
  const powerData = $derived(
    align(
      (tl?.samples ?? []).map((p) => [p.t, p.solar_w]),
      (tl?.plug ?? []).map((p) => [p.t, p.w ?? (p.on ? null : 0)]),
    ),
  );

  const health = $derived([
    { name: "Battery and emissions", t: s?.t, limit: 900, every: "every 5 min" },
    { name: "Plug", t: plug?.t, limit: 300, every: "every minute" },
    { name: "Plan", t: now?.plan?.generated_at, limit: 3 * 3600, every: "every 30 min" },
  ]);
  const stale = $derived(health.filter((h) => age(h.t) > h.limit));
</script>

<main>
  <header>
    <h1>Solar Farm</h1>
    <p class="sub">
      {#if stale.length}
        <span class="bad-dot"></span>{stale.map((h) => h.name).join(", ")} not reporting
      {:else if loadedAt}
        <span class="ok-dot"></span>Live · updated {ago(clock - loadedAt)}
      {/if}
    </p>
  </header>

  {#if error}
    <p class="banner">Couldn't refresh ({error}). Showing the last data.</p>
  {/if}

  <section class="card now" class:on={plug?.on} aria-labelledby="now-h">
    <div class="headline">
      <span class="dot" aria-hidden="true"></span>
      <div>
        <h2 id="now-h">{headline.title}</h2>
        <p>{headline.detail}.</p>
      </div>
    </div>
    <dl class="tiles">
      <div>
        <dt>Battery</dt>
        <dd><b>{s?.battery_pct ?? "–"}</b><small>%</small></dd>
        <dd class="n">Grid charges up to {RESERVE}%</dd>
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
        <dt>Grid emissions</dt>
        <dd><b>{s?.moer != null ? Math.round(s.moer) : "–"}</b><small>lb CO₂/MWh</small></dd>
        <dd class="n">
          {s?.index != null ? `Cleaner than ${Math.round(100 - s.index)}% of the past month` : ""}
        </dd>
      </div>
    </dl>
  </section>

  <section class="card" aria-labelledby="plan-h">
    <h2 id="plan-h">Plan</h2>
    <PlanView {windows} {forecast} now={tnow} generatedAt={now?.plan?.generated_at ?? null} />
  </section>

  <section class="card" aria-labelledby="em-h">
    <h2 id="em-h">Grid emissions</h2>
    <p class="lede">
      The marginal rate is the extra CO₂ from the next unit of power you use, and it's what the
      plan follows. In California it jumps between about 900 (gas) and near 0 (spare solar).
    </p>
    <TimeChart
      label="Grid emissions, past 24 hours and forecast"
      data={emissionsData}
      from={t0}
      to={t1}
      now={tnow}
      {windows}
      height={190}
      series={[
        { label: "Marginal, actual", color: "--ink", unit: "lb/MWh" },
        { label: "Marginal, forecast", color: "--accent", dash: [5, 4], unit: "lb/MWh" },
        { label: "Average, all plants", color: "--ink-3", width: 1.5, unit: "lb/MWh" },
      ]}
    />
  </section>

  <section class="card" aria-labelledby="acc-h">
    <div class="head">
      <h2 id="acc-h">How good is the forecast?</h2>
      <div class="seg" role="group" aria-label="Forecast made this long before">
        {#each LEADS as h (h)}
          <button aria-pressed={lead === h} onclick={() => pickLead(h)}>{h} h ahead</button>
        {/each}
      </div>
    </div>
    {#if acc && acc.compared > 0}
      <p class="lede">
        Made {hours(lead * 3600)} ahead, the forecast was off by
        <strong>{acc.error} lb/MWh</strong> on average over the last {acc.compared} readings.
      </p>
      <TimeChart
        label="Actual marginal emissions against the forecast made earlier"
        data={accuracyData}
        from={accFrom}
        to={tnow}
        now={tnow}
        height={160}
        series={[
          { label: "Actual", color: "--ink", unit: "lb/MWh" },
          { label: `Forecast from ${lead} h before`, color: "--accent", dash: [5, 4], unit: "lb/MWh" },
        ]}
      />
    {:else}
      <p class="lede">
        Every forecast is now being saved. Once one is {hours(lead * 3600)} old, this compares
        what it said with what actually happened.
      </p>
    {/if}
  </section>

  <section class="card" aria-labelledby="bat-h">
    <h2 id="bat-h">Battery and power</h2>
    <TimeChart
      label="Battery charge, past 24 hours"
      data={batteryData}
      from={t0}
      to={t1}
      now={tnow}
      {windows}
      height={130}
      yMax={100}
      yRule={{ value: RESERVE, label: `Grid charges up to ${RESERVE}%` }}
      series={[{ label: "Battery", color: "--accent", unit: "%" }]}
    />
    <div class="gap"></div>
    <TimeChart
      label="Solar and grid power into the battery, past 24 hours"
      data={powerData}
      from={t0}
      to={t1}
      now={tnow}
      {windows}
      height={130}
      series={[
        { label: "Solar", color: "--solar", fill: "--solar-fill", unit: "W" },
        { label: "Grid", color: "--grid", fill: "--grid-fill", unit: "W" },
      ]}
    />
    <p class="key">
      <span><i class="sw plan"></i>Planned grid charging</span>
      <span><i class="sw peak"></i>PG&amp;E peak, 4–9 PM</span>
    </p>
  </section>

  <div class="row">
    <section class="card" aria-labelledby="week-h">
      <div class="head">
        <h2 id="week-h">Last 7 days</h2>
        <button class="link" onclick={() => (weekTable = !weekTable)}>
          {weekTable ? "Show chart" : "Show table"}
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
      <p class="big">{RESERVE}%<small>set in the Jackery app</small></p>
      {#if daily?.reserve.reserve_pct != null}
        <p class="lede">
          Suggested: <strong>{daily.reserve.reserve_pct}%</strong>. That leaves room for a good
          solar day ({daily.reserve.good_day_wh} Wh) over the last {daily.reserve.days} full days.
        </p>
      {:else}
        <p class="lede">A suggestion appears after a few full days of readings.</p>
      {/if}
    </section>
  </div>

  <footer>
    {#each health as h (h.name)}
      <span class:stale={age(h.t) > h.limit} title="Expected {h.every}">
        <i></i>{h.name}: {h.t ? ago(age(h.t)) : "never"}
      </span>
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
  .ok-dot,
  .bad-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--good);
  }
  .bad-dot {
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
  .lede {
    margin: 0 0 10px;
    font-size: 13px;
    color: var(--ink-2);
    max-width: 70ch;
  }
  .lede strong {
    color: var(--ink);
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
  .dot {
    width: 14px;
    height: 14px;
    margin-top: 6px;
    border-radius: 50%;
    background: var(--ink-3);
    flex: none;
  }
  .now.on .dot {
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
  .gap {
    height: 12px;
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
  .big {
    font: 600 30px var(--f-display);
    margin: 0 0 6px;
  }
  .big small {
    margin-left: 8px;
    font: 400 13px var(--f-body);
    color: var(--ink-3);
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
