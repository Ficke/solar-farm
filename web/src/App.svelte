<script lang="ts">
  import { onMount } from "svelte";
  import { align, nearest } from "./lib/align";
  import { type Accuracy, api, type Co2, type Now, type Period, type Timeline } from "./lib/api";
  import Button from "./lib/Button.svelte";
  import { COUNTS } from "./lib/co2";
  import Hint from "./lib/Hint.svelte";
  import History from "./lib/History.svelte";
  import { FUTURE, LINE_THIN, PAST } from "./lib/layout";
  import { GROUPS, stackMix } from "./lib/mix";
  import PlanView from "./lib/PlanView.svelte";
  import PowerView from "./lib/PowerView.svelte";
  import { gridUse, MODES as PLAN, states } from "./lib/plan";
  import Segmented from "./lib/Segmented.svelte";
  import { explain } from "./lib/status";
  import TimeChart from "./lib/TimeChart.svelte";
  import { type Mode, setMode, theme, tintBrowser } from "./lib/theme.svelte";
  import { ago, fmtWhen, hours, PEAK_HOURS } from "./lib/time";
  import { RATE, rate } from "./lib/units";

  const MODES: { value: Mode; label: string }[] = [
    { value: "system", label: "System" },
    { value: "light", label: "Light" },
    { value: "dark", label: "Dark" },
  ];
  const LEADS = [1, 3, 6, 12].map((h) => ({ value: h, label: `${h} h` }));
  const CO2_RAMP: [number, string][] = [
    [115, "--co2-clean"],
    [250, "--co2-mid"],
    [385, "--co2-dirty"],
  ];
  // The stored rate holds until the charge changes, which can take hours.
  const STORED_GAP = 24 * 3600;
  const PERIODS = (Object.keys(COUNTS) as Period[]).map((p) => ({
    value: p,
    label: { day: "Daily", week: "Weekly", month: "Monthly" }[p],
  }));

  let now = $state<Now>();
  let tl = $state<Timeline>();
  let acc = $state<Accuracy>();
  let lead = $state(6);
  let view = $state<"impact" | "live">("impact");
  let forecastsOpen = $state(false);
  let accuracyOpen = $state(false);
  let gridOpen = $state(false);
  const VIEWS = [
    { value: "impact", label: "Energy & carbon" },
    { value: "live", label: "Live system" },
  ] as const;

  function switchTab(e: KeyboardEvent) {
    const index = VIEWS.findIndex((v) => v.value === view);
    const next =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? 1
          : e.key === "ArrowRight" || e.key === "ArrowLeft"
            ? 1 - index
            : null;
    if (next == null) return;
    e.preventDefault();
    view = VIEWS[next].value;
    document.getElementById(`tab-${view}`)?.focus();
  }
  let co2 = $state<Co2>();
  let by = $state<Period>("day");
  let error = $state("");
  let historyError = $state("");
  let clock = $state(Date.now() / 1000);

  // Ignore responses for selections that are no longer active.
  const fetchAccuracy = (h: number) =>
    api.accuracy(h).then((v) => {
      if (lead === h) acc = v;
    });
  const fetchCo2 = async (p: Period) => {
    try {
      const v = await api.co2(p, COUNTS[p]);
      if (by === p) {
        co2 = v;
        historyError = "";
      }
    } catch (e) {
      if (by === p) historyError = "History unavailable";
      throw e;
    }
  };

  async function run(jobs: Promise<unknown>[]) {
    try {
      await Promise.all(jobs);
      error = "";
      tick();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

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
    historyError = "";
    run([fetchCo2(p)]);
  }

  const tick = () => (clock = Date.now() / 1000);

  onMount(() => {
    tintBrowser();
    load("all");
    // Stagger polling on one timer; hidden tabs resume on visibility change.
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
  const windows = $derived(now?.plan?.windows ?? []);
  const blocks = $derived(now?.plan?.blocks ?? []);
  const forecast = $derived(tl?.forecast ?? []);
  const tnow = $derived(now?.now ?? clock);
  const plugStates = $derived(states(tl?.plug ?? [], tl?.samples ?? [], blocks, windows, tnow));
  const spans = $derived(gridUse(plugStates));
  // Keep charts and the plan strip on a shared time axis.
  const base = $derived(tl?.now ?? clock);
  const from = $derived(base - PAST);
  const to = $derived(base + FUTURE);
  const age = (t?: number | null) => (t ? clock - t : Infinity);

  // Name the state the plug is in now, from the same timeline as the plan strip.
  const headline = $derived.by(() => {
    if (!plug)
      return {
        title: now
          ? "Smart plug unavailable"
          : error
            ? "System status unavailable"
            : "Loading system status…",
        detail: "",
        mode: undefined,
      };
    const segs = plugStates;
    // What the plug reported up to now, else the plan for this moment.
    const at = (t: number) => segs.findIndex((g) => g.s <= t && t < g.e);
    const k = at(tnow - 1) >= 0 ? at(tnow - 1) : at(tnow);
    const mode = segs[k]?.mode;
    const title = explain(plug, mode);
    const next = k >= 0 ? segs.slice(k + 1).find((g) => g.mode !== mode) : undefined;
    const detail = next
      ? `Next: ${PLAN[next.mode].label} at ${fmtWhen(next.s, tnow)} for ${hours(next.e - next.s)}`
      : "";
    return { title, detail, mode };
  });

  const emissionsData = $derived(
    align(
      [
        (tl?.samples ?? []).map((p) => [p.moer_t ?? p.t, p.moer == null ? p.moer : rate(p.moer)]),
        [
          ...(acc?.points ?? []).map(
            ([t, , f]) => [t, f == null ? f : rate(f)] as [number, number | null],
          ),
          ...forecast.map(([t, v]) => [t, rate(v)] as [number, number]),
        ],
        (tl?.stored_co2 ?? []).map(([t, v]) => [t, rate(v)] as [number, number]),
      ],
      [15 * 60, 15 * 60, STORED_GAP],
    ),
  );
  const lastStored = $derived(tl?.stored_co2.at(-1)?.[1]);
  const stored = $derived(lastStored != null ? Math.round(rate(lastStored)) : null);
  const grid = $derived(s?.moer != null ? Math.round(rate(s.moer)) : null);
  const inUse = $derived.by(() => {
    if (!plug) return { value: null, source: "Unavailable" };
    const onGrid = headline.mode ? PLAN[headline.mode].on : plug.on;
    return { value: onGrid ? grid : stored, source: onGrid ? "Grid" : "Stored charge" };
  });
  const connected = $derived(nearest(tl?.load ?? [], s?.t ?? tnow, ([t]) => t)?.[1]);
  const overhead = $derived(nearest(tl?.overhead ?? [], s?.t ?? tnow, ([t]) => t)?.[1]);
  const mix = $derived(stackMix(tl?.mix ?? []));
  const priceData = $derived(
    align([
      (tl?.prices ?? []).map((p) => [p.t, p.np15]),
      (tl?.prices ?? []).map((p) => [p.t, p.sp15]),
    ]),
  );
  const batteryData = $derived(
    align([
      (tl?.samples ?? []).map((p) => [p.t, p.battery_pct]),
      [
        ...(blocks.length && s ? [[tnow, s.battery_pct] as [number, number | null]] : []),
        ...blocks.map((b) => [b.e, b.pct] as [number, number]),
      ],
    ]),
  );
  const powerData = $derived(
    align([
      (tl?.samples ?? []).map((p) => [p.t, p.solar_w]),
      (tl?.plug ?? []).map((p) => [p.t, p.w ?? (p.on ? null : 0)]),
      tl?.load ?? [],
      tl?.overhead ?? [],
    ]),
  );

  const health = $derived([
    { name: "Battery", t: s?.t, limit: 900 },
    { name: "Smart plug", t: plug?.t, limit: 300 },
    { name: "Plan", t: now?.plan?.generated_at, limit: 3 * 3600 },
    { name: "Forecast", t: now?.plan?.forecast_at, limit: 600 },
  ]);
  const stale = $derived(health.filter((h) => age(h.t) > h.limit));
  const liveDelayed = $derived(age(s?.t) > 900 || age(plug?.t) > 300);
  const liveTitle = $derived(
    plug && liveDelayed ? `Last reported: ${headline.title}` : headline.title,
  );
</script>

<main>
  <header>
    <div class="brand">
      <h1><i class="mark" aria-hidden="true"></i>Solar Farm</h1>
      <span>Jackery energy &amp; carbon</span>
    </div>
    <Segmented label="Theme" options={MODES} value={theme.mode} onpick={setMode} />
  </header>

  <div class="tabs" role="tablist" aria-label="Dashboard view">
    {#each VIEWS as v (v.value)}
      <button type="button" role="tab" id="tab-{v.value}" aria-controls="panel-{v.value}"
        aria-selected={view === v.value} tabindex={view === v.value ? 0 : -1}
        onclick={() => (view = v.value)} onkeydown={switchTab}>{v.label}</button>
    {/each}
  </div>

  {#if error}
    <div class="banner" role="alert"><span>Refresh failed</span><Hint text={error}>Details</Hint><Button onclick={() => load("all")}>Retry</Button></div>
  {/if}
  {#if now && stale.length}
    <p class="data-alert" role="status">Delayed or unavailable: {stale.map((h) => h.name.toLowerCase()).join(", ")}</p>
  {/if}

  <div id="panel-impact" role="tabpanel" aria-labelledby="tab-impact" tabindex="0" hidden={view !== "impact"}>
  {#if view === "impact"}
  <section id="impact" class="card report" aria-labelledby="hist-h">
    <div class="head">
      <div><h2 id="hist-h">Energy &amp; carbon</h2><p class="scope">Last {COUNTS[by]} {by}s · <Hint text="The current day, week or month is still in progress. Totals cover periods with readings.">Current {by} in progress</Hint></p></div>
      <div class="ctl">{#if historyError}<Button onclick={() => run([fetchCo2(by)])}>Retry history</Button>{/if}<span class="stat">Group by</span><Segmented label="Group history by" options={PERIODS} value={by} onpick={pickPeriod} /></div>
    </div>
    <History {by} error={historyError} co2={co2?.by === by ? co2 : undefined} now={tnow} />
  </section>

  {/if}
  </div>
  <div id="panel-live" class="live-panel" role="tabpanel" aria-labelledby="tab-live" tabindex="0" hidden={view !== "live"}>
  {#if view === "live"}
  <section id="live" class="card" aria-labelledby="live-h">
    <div class="head">
      <h2 id="live-h">Live system</h2>
      <span class="scope" class:delayed={now && liveDelayed}>{!now ? "Awaiting readings" : liveDelayed ? "Delayed readings" : "Latest readings"}</span>
    </div>
    <div class="headline">
      <span class="state {headline.mode ?? ''}" aria-hidden="true"></span>
      <div>
        <h3>{liveTitle}</h3>
        {#if headline.detail}<p>{headline.detail}</p>{/if}
      </div>
    </div>
    <dl class="tiles">
      <div>
        <dt>Battery charge</dt>
        <dd><b>{s?.battery_pct ?? "–"}</b><small>%</small></dd>
        <dd class="gauge" aria-hidden="true"><i style:width="{s?.battery_pct ?? 0}%"></i></dd>
      </div>
      <div>
        <dt><i class="sw solar"></i>Solar input</dt>
        <dd><b>{s?.solar_w ?? "–"}</b><small>W</small></dd>
      </div>
      <div>
        <dt><i class="sw grid"></i>Grid input</dt>
        <dd><b>{plug?.w != null ? Math.round(plug.w) : "–"}</b><small>W</small></dd>
      </div>
      <div>
        <dt><i class="sw load"></i><Hint text="Estimated power used by appliances connected to the Jackery’s outputs. Excludes the Jackery’s own draw.">Connected load</Hint></dt>
        <dd><b>{connected != null ? Math.round(connected) : "–"}</b><small>W</small></dd>
        <dd class="n">Battery overhead {overhead != null ? `${Math.round(overhead)} W` : "–"}</dd>
      </div>
    </dl>
    <PowerView data={powerData} {from} to={base} now={tnow} windows={spans} />
  </section>

  <section id="plan" class="card charts" aria-labelledby="plan-h">
    <div class="head"><h2 id="plan-h">Charging plan</h2><span class="scope">Past 24 h · Next 24 h</span></div>
    {#if now?.plan?.strategy === "adaptive"}
      {@const p = now.plan}
      {@const by = p.deadline ? fmtWhen(p.deadline, tnow) : "4 PM"}
      {@const goal = (p.target_pct ?? 100) >= 99.5 ? "full" : `${Math.round(p.target_pct ?? 100)}%`}
      <p class="outcome" class:short={!!p.shortfall_wh}>
        <span>Charge target</span>
        <Hint
          text={goal === "full"
            ? `Charges to full before the ${PEAK_HOURS} peak, using the cleanest grid hours.`
            : `Charges before the ${PEAK_HOURS} peak, leaving room for tomorrow's solar.`}
          >{p.shortfall_wh
            ? `${p.shortfall_wh} Wh short of ${goal} by ${by}`
            : `${goal === "full" ? "Full" : goal} by ${by}`}</Hint
        >{#if p.grid_wh && !p.shortfall_wh}<span>, {p.grid_wh} Wh from grid</span>{/if}
      </p>
    {:else if now?.plan?.strategy === "fallback"}
      <p class="n">Fixed schedule, no battery data</p>
    {/if}

    {#if now?.plan}
      <PlanView {blocks} states={plugStates} samples={tl?.samples ?? []} {forecast} {from} {to} now={tnow} />
    {:else}<p class="n">{now ? "No charging plan available" : "Loading charging plan…"}</p>{/if}
    <details class="disclosure" bind:open={forecastsOpen}>
      <summary>Battery &amp; carbon forecasts</summary>
      <div class="detail-body">
        <h3>Battery charge, %</h3>
    <TimeChart
      label="Battery charge, past 24 hours and next 24 hours planned"
      title="Charge, %"
      data={batteryData}
      {from}
      {to}
      now={tnow}
      windows={spans}
      height={110}
      yMax={100}
      series={[
        { label: "Battery", color: "--battery", unit: "%" },
        { label: "Plan", color: "--battery", dash: [4, 4], width: LINE_THIN, unit: "%" },
      ]}
    />

        <div class="head"><h3><Hint text="Emissions per unit of electricity. Lower values mean cleaner power.">Carbon intensity, {RATE}</Hint></h3><span class="scope">Lower is cleaner</span></div>
        <dl class="comparison">
          <div><dt>Grid now</dt><dd>{grid ?? "–"}<small>{RATE}</small></dd></div>
          <div><dt>Stored charge</dt><dd>{stored ?? "–"}<small>{RATE}</small></dd></div>
          <div><dt><Hint text="CO₂ per kWh supplied to connected appliances, based on the current power source.">In use · {inUse.source}</Hint></dt><dd>{inUse.value ?? "–"}<small>{RATE}</small></dd></div>
        </dl>
    <TimeChart
      label="Marginal CO2, past 24 hours and forecast, and battery CO2"
      title={`Carbon intensity, ${RATE}`}
      data={emissionsData}
      {from}
      {to}
      now={tnow}
      windows={spans}
      height={180}
      series={[
        { label: "Grid actual", color: "--co2-mid", ramp: CO2_RAMP, unit: RATE },
        {
          label: "Grid forecast",
          color: "--co2-mid",
          ramp: CO2_RAMP,
          dash: [4, 4],
          width: LINE_THIN,
          unit: RATE,
        },
        { label: "Stored charge", color: "--battery", unit: RATE, hold: true },
      ]}
    />

        <details class="disclosure diagnostic" bind:open={accuracyOpen}><summary>Forecast accuracy</summary>
      <div class="ctl">
        <span class="stat"
          ><Hint text="How far the CO₂ forecast was off, on average, over the last 24 hours.">Forecast error</Hint></span
        >
        <Segmented label="Hours ahead" options={LEADS} value={lead} onpick={pickLead} />
        <span class="stat"><b>{acc?.error != null ? Math.round(rate(acc.error)) : "–"}</b> {RATE}</span>
      </div>

        </details>
      </div>
    </details>
  </section>

  <section id="grid" class="card charts" aria-labelledby="grid-h">
    <h2 id="grid-h">Grid details</h2>
    <details class="disclosure" bind:open={gridOpen}>
      <summary>California generation &amp; wholesale prices <span class="scope">Past 24 h</span></summary>
      <div class="detail-body">
    <h3>California generation by source, GW</h3>
    <TimeChart
      label="California generation by source, past 24 hours"
      title="California generation by source, GW"
      data={mix.stacked}
      tipData={mix.raw}
      shade={false}
      {from}
      to={base}
      now={tnow}
      height={160}
      series={GROUPS.map((g) => ({
        label: g.label,
        color: g.color,
        fill: g.color,
        area: true,
        width: LINE_THIN,
        unit: "GW",
        digits: 1,
      }))}
    />
    <h3>Wholesale price, $/MWh</h3>
    <TimeChart
      label="Wholesale real-time price, north and south, past 24 hours"
      title="Wholesale price, $/MWh"
      data={priceData}
      shade={false}
      {from}
      to={base}
      now={tnow}
      height={120}
      series={[
        { label: "North", color: "--ink", unit: "$/MWh", digits: 0 },
        { label: "South", color: "--load", width: LINE_THIN, unit: "$/MWh", digits: 0 },
      ]}
    />

      </div>
    </details>
  </section>

  {/if}
  </div>

  <footer aria-label="Data freshness">
    {#each health as h (h.name)}
      <span class:stale={age(h.t) > h.limit}><i></i>{h.name} {h.t ? ago(age(h.t)) : "unavailable"}</span>
    {/each}
  </footer>
</main>

<style>
  main { max-width: 1080px; margin: 0 auto; display: grid; gap: var(--space-8); }
  header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px; }
  .brand { display: grid; gap: 2px; }
  .brand > span { font-size: 12px; color: var(--ink-3); }
  h1 { display: flex; align-items: center; gap: 8px; font: 600 16px var(--f-sans); margin: 0; }
  .mark { width: 10px; height: 10px; border-radius: var(--radius-key); background: var(--solar); }
  .tabs { display: flex; flex-wrap: nowrap; overflow-x: auto; gap: var(--space-6); margin-top: -12px; border-bottom: 1px solid var(--line); }
  .tabs button { color: var(--ink-3); background: transparent; border: 0; border-radius: 0; font-size: var(--text-control); font-weight: 500; min-height: var(--touch-target); flex: none; padding: 10px 0; border-bottom: 2px solid transparent; }
  .tabs button:focus-visible { outline-offset: -3px; }
  .tabs button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--ink); }
  [hidden] { display: none; }
  .live-panel { display: grid; gap: var(--space-8); min-width: 0; }
  .live-panel > section:first-child { border-top: 0; padding-top: 0; }
  .tabs button:hover { color: var(--ink); }
  [role="tabpanel"]:focus-visible, .tabs button:focus-visible, summary:focus-visible { outline: 2px solid var(--grid); outline-offset: 4px; border-radius: var(--radius-key); }
  section[id] { scroll-margin-top: 20px; }
  h2 { font: 600 var(--text-section) var(--f-sans); letter-spacing: -0.015em; margin: 0; }
  h3 { font: 500 13px var(--f-sans); color: var(--ink-2); margin: 20px 0 6px; }
  .card { border-top: 1px solid var(--line); padding-top: var(--space-6); min-width: 0; }
  .report { border: 0; padding-top: 0; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px 20px; flex-wrap: wrap; margin-bottom: 14px; }
  .head h3 { margin: 0; }
  .scope { font-size: 12px; font-weight: 400; color: var(--ink-3); }
  p.scope { margin: 5px 0 0; }
  .scope.delayed { color: var(--bad-ink); }
  .ctl { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .stat { font-size: 13px; color: var(--ink-3); }
  .stat b { color: var(--ink); font-weight: 600; }
  .headline { display: flex; gap: 12px; align-items: baseline; }
  .headline h3 { font-size: var(--text-status); font-weight: 500; letter-spacing: -0.02em; line-height: 1.2; margin: 0; color: var(--ink); }
  .headline p { margin: 5px 0 0; font-size: 14px; color: var(--ink-2); }
  .state { width: 11px; height: 11px; border-radius: 50%; border: 2px solid var(--ink-3); flex: none; transform: translateY(-2px); }
  .state.charge { border-color: var(--plan-charge); background: var(--plan-charge); box-shadow: 0 0 0 4px var(--grid-fill); }
  .state.bypass { border-color: var(--plan-bypass); background: var(--plan-bypass); }
  .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 24px 0 28px; }
  .tiles > div { padding: 2px 20px; border-left: 1px solid var(--line); min-width: 0; }
  .tiles > div:first-child { padding-left: 0; border-left: 0; }
  dt { font-size: 13px; font-weight: 500; color: var(--ink-2); display: flex; align-items: center; gap: 6px; }
  dd { margin: 0; }
  dd b { font: 500 var(--text-metric-mobile) / 1.2 var(--f-sans); letter-spacing: -0.025em; }
  dd small { font-size: 13px; margin-left: 5px; color: var(--ink-3); }
  .gauge { height: 4px; margin: 8px 0 2px; border-radius: var(--radius-control); background: var(--panel-2); overflow: hidden; }
  .gauge i { display: block; height: 100%; background: var(--ink); border-radius: var(--radius-control); }
  .n { font-size: 12px; color: var(--ink-3); }
  .outcome { margin: 0 0 16px; font-size: 20px; font-weight: 500; }
  .outcome span { font-size: 14px; font-weight: 400; color: var(--ink-2); }
  .outcome.short { color: var(--bad-ink); }
  .sw { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: var(--radius-key); }
  .sw.solar { background: var(--solar); }
  .sw.grid { background: var(--grid); }
  .sw.load { background: var(--load); }
  .disclosure { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 12px; }
  summary { cursor: pointer; font-size: 13px; font-weight: 500; color: var(--ink-2); padding: 4px 0; }
  summary .scope { margin-left: 8px; }
  .detail-body { padding-top: 8px; min-width: 0; }
  .detail-body > h3:first-child { margin-top: 4px; }
  .detail-body > .head { margin-top: 24px; }
  .comparison { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0; }
  .comparison dd { font-size: 20px; }
  .comparison small { font-size: 12px; }
  .diagnostic .ctl { margin-top: 10px; }
  .banner { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 10px 14px; border-radius: var(--radius-surface); background: var(--bad-bg); color: var(--bad-ink); font-size: 13px; }
  .banner > span { margin-right: auto; }
  .data-alert { margin: -12px 0 0; font-size: 13px; color: var(--bad-ink); }
  footer { display: flex; gap: 8px 16px; flex-wrap: wrap; font-size: 12px; color: var(--ink-3); border-top: 1px solid var(--line); padding-top: 12px; margin-top: -8px; }
  footer i { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--good); margin: 0 6px 1px 0; }
  footer .stale { color: var(--bad-ink); }
  footer .stale i { background: var(--bad); }
  @media (max-width: 640px) {
    main { gap: 28px; }
    header { align-items: flex-start; }
    .tabs { gap: 6px 18px; }
    .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 20px; margin-top: 20px; }
    .tiles > div { padding: 2px 16px; }
    .tiles > div:nth-child(3) { padding-left: 0; border-left: 0; }
    .headline h3 { font-size: 22px; }
    .tiles dd b { font-size: 28px; }
    .comparison { grid-template-columns: 1fr; gap: 8px; }
    .comparison > div { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  }
</style>
