<script lang="ts">
  import { onMount } from "svelte";
  import { align } from "./lib/align";
  import { api, type Daily, type Now, type Timeline } from "./lib/api";
  import { explain, upcoming } from "./lib/status";
  import TimeChart from "./lib/TimeChart.svelte";
  import { ago, fmtDayClock } from "./lib/time";
  import WeekBars from "./lib/WeekBars.svelte";

  const RESERVE = 80; // set by hand in the Jackery app
  const FUTURE = 24 * 3600;

  let now = $state<Now>();
  let tl = $state<Timeline>();
  let daily = $state<Daily>();
  let error = $state("");
  let clock = $state(Date.now() / 1000);

  async function load(what: "now" | "all") {
    try {
      const jobs: Promise<unknown>[] = [api.now().then((v) => (now = v))];
      if (what === "all") {
        jobs.push(api.timeline(24).then((v) => (tl = v)));
        jobs.push(api.daily(14).then((v) => (daily = v)));
      }
      await Promise.all(jobs);
      error = "";
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    load("all");
    const timers = [
      setInterval(() => load("now"), 30_000),
      setInterval(() => load("all"), 5 * 60_000),
      setInterval(() => (clock = Date.now() / 1000), 10_000),
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
  const t0 = $derived(tl?.since ?? clock - 24 * 3600);
  const t1 = $derived((tl?.now ?? clock) + FUTURE);
  const tnow = $derived(now?.now ?? clock);
  const next = $derived(upcoming(windows, tnow, 3));
  const age = (t?: number | null) => (t ? clock - t : Infinity);

  const moerData = $derived(
    align(
      (tl?.samples ?? []).map((p) => [p.t, p.moer]),
      (tl?.forecast ?? []).map(([t, v]) => [t, v]),
    ),
  );
  const batteryData = $derived(align((tl?.samples ?? []).map((p) => [p.t, p.battery_pct])));
  const powerData = $derived(
    align(
      (tl?.samples ?? []).map((p) => [p.t, p.solar_w]),
      (tl?.plug ?? []).map((p) => [p.t, p.w ?? (p.on ? null : 0)]),
    ),
  );

  const health = $derived([
    { name: "Battery", t: s?.t, limit: 900 },
    { name: "Plug", t: plug?.t, limit: 300 },
    { name: "Plan", t: now?.plan?.generated_at, limit: 3 * 3600 },
  ]);
</script>

<main>
  <header>
    <h1>Solar Farm</h1>
    <span class="sub">{fmtDayClock(tnow)} Pacific</span>
  </header>

  {#if error}
    <p class="banner bad">Couldn't refresh: {error}. Showing the last data.</p>
  {/if}

  <section class="status" class:on={plug?.on}>
    {#if plug}
      <span class="dot"></span>
      <div>
        <strong>Grid {plug.on ? "on" : "off"}.</strong>
        {explain(plug, windows, tnow)}.
      </div>
    {:else}
      <div>Waiting for the plug's first report.</div>
    {/if}
    {#if next.length}
      <ul class="next">
        {#each next as c (c.t + c.label)}
          <li class:peak={c.peak}>{c.label}</li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="tiles">
    <div class="tile">
      <span class="k">Battery</span>
      <span class="v">{s?.battery_pct ?? "–"}<small>%</small></span>
      <span class="n">Reserve {RESERVE}%</span>
    </div>
    <div class="tile">
      <span class="k">Solar now</span>
      <span class="v solar">{s?.solar_w ?? "–"}<small>W</small></span>
      <span class="n">{now ? `${now.today.solar_wh} Wh today` : ""}</span>
    </div>
    <div class="tile">
      <span class="k">Grid now</span>
      <span class="v grid">{plug?.w != null ? Math.round(plug.w) : "–"}<small>W</small></span>
      <span class="n">{now ? `${now.today.grid_wh} Wh today` : ""}</span>
    </div>
    <div class="tile">
      <span class="k">Grid emissions</span>
      <span class="v">{s?.moer != null ? Math.round(s.moer) : "–"}<small>lb/MWh</small></span>
      <span class="n">{s?.index != null ? `Cleaner than ${100 - s.index}% of the past month` : "WattTime MOER"}</span>
    </div>
  </section>

  <section class="card">
    <h2>Grid emissions <span class="hint">measured, then WattTime's forecast</span></h2>
    <TimeChart
      data={moerData}
      from={t0}
      to={t1}
      now={tnow}
      {windows}
      series={[
        { label: "Measured", color: "--ink-2", unit: "lb/MWh" },
        { label: "Forecast", color: "--accent", dash: [5, 4], unit: "lb/MWh" },
      ]}
    />
    <h2>Battery</h2>
    <TimeChart
      data={batteryData}
      from={t0}
      to={t1}
      now={tnow}
      {windows}
      height={120}
      yMax={100}
      yRule={{ value: RESERVE, label: `reserve ${RESERVE}%` }}
      series={[{ label: "Charge", color: "--good", unit: "%" }]}
    />
    <h2>Power in</h2>
    <TimeChart
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
    <p class="legend">
      <span class="sw plan"></span>Planned grid charging
      <span class="sw peak"></span>PG&amp;E peak, 4–9 pm
    </p>
  </section>

  <div class="row">
    <section class="card">
      <h2>Last 7 days <span class="hint"><i class="sw solar"></i>solar <i class="sw grid"></i>grid</span></h2>
      <WeekBars days={daily?.days ?? []} />
    </section>
    <section class="card">
      <h2>Reserve</h2>
      {#if daily?.reserve.reserve_pct != null}
        <p class="big">{daily.reserve.reserve_pct}%</p>
        <p class="muted">
          Suggested from the last {daily.reserve.days} full days of solar
          {#if daily.reserve.good_day_wh}(a good day is about {daily.reserve.good_day_wh} Wh){/if}.
          Currently set to {RESERVE}% in the Jackery app.
        </p>
      {:else}
        <p class="muted">A suggestion appears after a few full days of readings. Currently {RESERVE}%.</p>
      {/if}
    </section>
  </div>

  <section class="health">
    {#each health as h (h.name)}
      <span class:stale={age(h.t) > h.limit}>
        <i></i>{h.name} {h.t ? ago(age(h.t)) : "never"}
      </span>
    {/each}
  </section>
</main>

<style>
  main {
    max-width: 1080px;
    margin: 0 auto;
    display: grid;
    gap: 14px;
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
    font: 600 14px var(--f-body);
    margin: 14px 0 4px;
    color: var(--ink-2);
  }
  h2:first-child {
    margin-top: 0;
  }
  .sub,
  .hint,
  .muted {
    color: var(--ink-3);
    font-size: 13px;
    font-weight: 400;
  }
  .card,
  .status,
  .tile {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 14px 16px;
    min-width: 0;
  }
  .banner {
    margin: 0;
    padding: 10px 14px;
    border-radius: 8px;
  }
  .bad {
    background: var(--bad-bg);
    color: var(--bad);
  }
  .status {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .status .dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--ink-3);
    flex: none;
  }
  .status.on .dot {
    background: var(--grid);
    box-shadow: 0 0 0 4px var(--grid-fill);
  }
  .status > div {
    flex: 1 1 260px;
  }
  .next {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .next li {
    font: 12px var(--f-mono);
    padding: 3px 8px;
    border-radius: 6px;
    background: var(--plan-band);
    color: var(--ink-2);
  }
  .next li.peak {
    background: var(--peak-band);
    color: var(--peak-ink);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 14px;
  }
  .tile {
    display: grid;
    gap: 2px;
  }
  .k {
    font-size: 13px;
    color: var(--ink-3);
  }
  .v {
    font: 600 30px var(--f-display);
    font-variant-numeric: tabular-nums;
  }
  .v small {
    font-size: 14px;
    margin-left: 3px;
    color: var(--ink-3);
    font-weight: 400;
  }
  .v.solar {
    color: var(--solar);
  }
  .v.grid {
    color: var(--grid);
  }
  .n {
    font-size: 13px;
    color: var(--ink-2);
  }
  .row {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 14px;
  }
  @media (max-width: 720px) {
    .row {
      grid-template-columns: 1fr;
    }
  }
  .big {
    font: 600 34px var(--f-display);
    margin: 4px 0;
  }
  .legend {
    margin: 8px 0 0;
    font-size: 12px;
    color: var(--ink-3);
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .sw {
    display: inline-block;
    width: 12px;
    height: 10px;
    border-radius: 2px;
    vertical-align: -1px;
    margin-left: 6px;
  }
  .sw.plan {
    background: var(--plan-band);
    border: 1px solid var(--grid);
  }
  .sw.peak {
    background: var(--peak-band);
    border: 1px solid var(--peak-ink);
  }
  .sw.solar {
    background: var(--solar);
  }
  .sw.grid {
    background: var(--grid);
  }
  .health {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font: 12px var(--f-mono);
    color: var(--ink-3);
  }
  .health i {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--good);
    margin-right: 6px;
  }
  .health .stale {
    color: var(--bad);
  }
  .health .stale i {
    background: var(--bad);
  }
</style>
