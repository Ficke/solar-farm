"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const acorn = require("acorn");
const { load, SOURCE } = require("./harness");

const NOW = 1790000000;

function freshState(ctx, overrides = {}) {
  return Object.assign(
    { plan: null, index: null, indexAt: 0, lastOnAt: NOW - 60, safetyUntil: 0, on: false },
    overrides
  );
}

test("script parses as ES5 so the Shelly interpreter can run it", () => {
  assert.doesNotThrow(() => acorn.parse(SOURCE, { ecmaVersion: 5 }));
});

test("peak hours always block the grid, even when the plan says on", () => {
  const { context } = load();
  const s = freshState(context, {
    plan: { generated_at: NOW - 60, windows: [[NOW - 100, NOW + 100]] },
    lastOnAt: NOW - 31 * 3600
  });
  for (const t of ["16:00", "18:30", "20:59"]) {
    const d = context.decide(s, NOW, context.parseLocalMinutes(t), context.CFG);
    assert.deepEqual({ ...d }, { on: false, reason: "peak" }, t);
  }
  const after = context.decide(s, NOW, context.parseLocalMinutes("21:00"), context.CFG);
  assert.equal(after.on, true);
});

test("a fresh plan decides by its windows", () => {
  const { context } = load();
  const s = freshState(context, {
    plan: { generated_at: NOW - 600, windows: [[NOW - 100, NOW + 100]] }
  });
  assert.deepEqual({ ...context.decide(s, NOW, 720, context.CFG) }, { on: true, reason: "plan" });
  assert.equal(context.decide(s, NOW + 200, 724, context.CFG).on, false);
});

test("a stale plan falls back to the live index with hysteresis", () => {
  const { context } = load();
  const base = { plan: { generated_at: NOW - 4 * 3600, windows: [] }, indexAt: NOW - 60 };
  const off = freshState(context, { ...base, index: 28, on: false });
  assert.deepEqual({ ...context.decide(off, NOW, 720, context.CFG) }, { on: false, reason: "index" });
  const on = freshState(context, { ...base, index: 28, on: true });
  assert.equal(context.decide(on, NOW, 720, context.CFG).on, true);
  const clean = freshState(context, { ...base, index: 10 });
  assert.equal(context.decide(clean, NOW, 720, context.CFG).on, true);
});

test("no plan and no index uses the 10am to 3pm window", () => {
  const { context } = load();
  const s = freshState(context);
  assert.deepEqual({ ...context.decide(s, NOW, 9 * 60 + 59, context.CFG) }, { on: false, reason: "fallback" });
  assert.equal(context.decide(s, NOW, 10 * 60, context.CFG).on, true);
  assert.equal(context.decide(s, NOW, 15 * 60, context.CFG).on, false);
});

test("30 hours off forces the grid on, but not during peak", () => {
  const { context } = load();
  const s = freshState(context, {
    plan: { generated_at: NOW - 60, windows: [] },
    lastOnAt: NOW - 30 * 3600 - 1
  });
  assert.deepEqual({ ...context.decide(s, NOW, 23 * 60, context.CFG) }, { on: true, reason: "safety" });
  assert.equal(context.decide(s, NOW, 17 * 60, context.CFG).reason, "peak");
});

test("unknown time keeps the grid off", () => {
  const { context } = load();
  assert.equal(context.parseLocalMinutes(null), -1);
  assert.deepEqual({ ...context.decide(freshState(context), NOW, -1, context.CFG) }, { on: false, reason: "no-time" });
});

test("a recent feasible adaptive plan permits solar-only operation beyond 30 hours", () => {
  const { context } = load();
  const plan = { generated_at: NOW - 60, strategy: "adaptive", shortfall_wh: 0, windows: [] };
  const s = freshState(context, { plan, lastOnAt: NOW - 31 * 3600, safetyUntil: NOW + 600 });
  assert.deepEqual({ ...context.decide(s, NOW, 720, context.CFG) }, { on: false, reason: "plan" });
  assert.equal(context.decide(s, NOW + 901, 735, context.CFG).reason, "safety");
  s.plan.shortfall_wh = 100;
  assert.equal(context.decide(s, NOW, 720, context.CFG).reason, "safety");
});

test("startup reads config from KVS, follows the plan and logs a charge session", () => {
  const plan = { generated_at: NOW - 60, windows: [[NOW - 60, NOW + 60]] };
  const h = load({
    time: "11:00",
    kvs: {
      "gg.plan_url": "https://solar-edge.example.run.app/plug/plan",
      "gg.cfg": JSON.stringify({ threshold: 30 })
    },
    responses: { "HTTP.GET": { code: 200, body: JSON.stringify(plan) } }
  });
  const { context, calls, timers, endpoints, device } = h;
  assert.equal(context.CFG.threshold, 30);
  assert.equal(timers.length, 1);
  assert.ok(endpoints.status);

  // First tick fetched the plan before deciding, so the grid is on.
  assert.ok(calls.some((c) => c.method === "HTTP.GET"));
  assert.equal(device.sw.output, true);
  assert.equal(context.S.reason, "plan");

  // Window closes: grid off, session recorded with the metered energy.
  device.sw.aenergy.total = 840;
  device.sys.unixtime = NOW + 120;
  timers[0].fn();
  assert.equal(device.sw.output, false);
  assert.equal(context.S.sessions.length, 1);
  assert.equal(context.S.sessions[0].wh, 840);

  let body = null;
  endpoints.status({}, { send() { body = JSON.parse(this.body); } });
  assert.equal(body.on, false);
  assert.equal(body.sessions[0].wh, 840);
});

test("KVS results are read in both firmware formats", () => {
  const { context } = load();
  assert.deepEqual({ ...context.kvsItems({ items: [{ key: "a", value: "1" }] }) }, { a: "1" });
  assert.deepEqual({ ...context.kvsItems({ items: { a: { etag: "x", value: "1" } } }) }, { a: "1" });
});

test("with a plug key, the plan request carries it and every tick posts a report", () => {
  const plan = { generated_at: NOW - 60, windows: [[NOW - 60, NOW + 60]] };
  const h = load({
    time: "11:00",
    kvs: {
      "gg.plan_url": "https://solar-edge.example.run.app/plug/plan",
      "gg.report_url": "https://solar-edge.example.run.app/plug/report",
      "gg.plug_key": "k3y"
    },
    responses: {
      "HTTP.Request": (p) => (p.method === "GET" ? { code: 200, body: JSON.stringify(plan) } : { code: 204 })
    }
  });
  const { calls, device } = h;
  device.sw.apower = 412.5;
  const reqs = calls.filter((c) => c.method === "HTTP.Request");
  const get = reqs.find((c) => c.params.method === "GET");
  assert.equal(get.params.url, "https://solar-edge.example.run.app/plug/plan");
  assert.equal(get.params.headers["X-Plug-Key"], "k3y");
  assert.ok(!calls.some((c) => c.method === "HTTP.GET"));

  const post = reqs.find((c) => c.params.method === "POST");
  assert.equal(post.params.url, "https://solar-edge.example.run.app/plug/report?plan=1");
  assert.equal(post.params.headers["X-Plug-Key"], "k3y");
  const body = JSON.parse(post.params.body);
  assert.equal(body.t, NOW);
  assert.equal(body.on, true);
  assert.equal(body.reason, "plan");
  assert.equal(body.plan_at, NOW - 60);
});

test("no report is sent without a report URL", () => {
  const h = load({ kvs: { "gg.plug_key": "k3y" } });
  assert.ok(!h.calls.some((c) => c.method === "HTTP.Request" && c.params.method === "POST"));
});

test("plan and index fetches never share a tick", () => {
  const h = load({
    kvs: {
      "gg.plan_url": "https://solar-edge.example.run.app/plug/plan",
      "gg.report_url": "https://solar-edge.example.run.app/plug/report",
      "gg.plug_key": "k3y",
      "gg.wt_auth": "dXNlcjpwYXNz"
    },
    responses: {
      "HTTP.Request": (p) => ({ code: p.method === "POST" ? 204 : 503, body: "" })
    }
  });

  const startupUrls = h.calls
    .filter((c) => c.method === "HTTP.Request")
    .map((c) => c.params.url);
  assert.deepEqual(startupUrls, [
    "https://solar-edge.example.run.app/plug/plan",
    "https://solar-edge.example.run.app/plug/report?plan=1"
  ]);

  for (let i = 0; i < 5; i++) h.timers[0].fn();
  const latestUrls = h.calls
    .filter((c) => c.method === "HTTP.Request")
    .slice(-2)
    .map((c) => c.params.url);
  assert.deepEqual(latestUrls, [
    "https://api.watttime.org/login",
    "https://solar-edge.example.run.app/plug/report?plan=1"
  ]);
});

test("the plan comes back with each report and is followed on the next tick", () => {
  let plan = { generated_at: NOW - 60, windows: [] };
  const h = load({
    time: "08:00",
    kvs: {
      "gg.plan_url": "https://solar-edge.example.run.app/plug/plan",
      "gg.report_url": "https://solar-edge.example.run.app/plug/report",
      "gg.plug_key": "k3y"
    },
    responses: {
      "HTTP.Request": (p) =>
        p.method === "POST" ? { code: 200, body: JSON.stringify(plan) } : { code: 503, body: "" }
    }
  });
  assert.equal(h.device.sw.output, false);
  // The server replans: a window from now. The next report brings it back.
  plan = { generated_at: NOW, windows: [[NOW, NOW + 600]] };
  h.timers[0].fn(); // decides with the old plan, then reports and gets the new one
  h.timers[0].fn();
  assert.equal(h.device.sw.output, true);
  // While reports bring plans, the plug never fetches /plug/plan on its own.
  const gets = h.calls.filter((c) => c.method === "HTTP.Request" && c.params.method === "GET");
  assert.equal(gets.length, 1); // the one at startup
  for (let i = 0; i < 20; i++) h.timers[0].fn();
  assert.equal(
    h.calls.filter((c) => c.method === "HTTP.Request" && c.params.method === "GET").length,
    1
  );
});

test("an older server's 204 reply is not a failure, and the plan fetch still runs", () => {
  const plan = { generated_at: NOW - 60, windows: [[NOW - 60, NOW + 60]] };
  const h = load({
    time: "11:00",
    kvs: {
      "gg.plan_url": "https://solar-edge.example.run.app/plug/plan",
      "gg.report_url": "https://solar-edge.example.run.app/plug/report",
      "gg.plug_key": "k3y"
    },
    responses: {
      "HTTP.Request": (p) => (p.method === "GET" ? { code: 200, body: JSON.stringify(plan) } : { code: 204 })
    }
  });
  h.device.sys.unixtime = NOW + 600;
  for (let i = 0; i < 10; i++) h.timers[0].fn();
  const gets = h.calls.filter((c) => c.method === "HTTP.Request" && c.params.method === "GET");
  assert.equal(gets.length, 2);
});

test("once on, a gap of a few minutes before the next window keeps the grid on", () => {
  const { context } = load();
  const plan = { generated_at: NOW - 60, windows: [[NOW - 600, NOW], [NOW + 120, NOW + 900]] };
  const on = freshState(context, { plan, on: true });
  assert.deepEqual({ ...context.decide(on, NOW, 720, context.CFG) }, { on: true, reason: "plan" });
  // Off already: it waits for the window rather than starting early.
  const off = freshState(context, { plan, on: false });
  assert.equal(context.decide(off, NOW, 720, context.CFG).on, false);
  // A longer gap is a planned stop.
  const later = { generated_at: NOW - 60, windows: [[NOW - 600, NOW], [NOW + 600, NOW + 900]] };
  assert.equal(context.decide(freshState(context, { plan: later, on: true }), NOW, 720, context.CFG).on, false);
});

test("a failed relay change is retried on the next tick", () => {
  const plan = { generated_at: NOW - 60, windows: [[NOW - 60, NOW + 120]] };
  const h = load({
    switchSetFails: true,
    kvs: { "gg.plan_url": "https://example.com/plan" },
    responses: { "HTTP.GET": { code: 200, body: JSON.stringify(plan) } }
  });

  assert.equal(h.device.sw.output, false);
  assert.equal(h.calls.filter((c) => c.method === "Switch.Set").length, 1);

  h.device.sys.unixtime = NOW + 60;
  h.timers[0].fn();
  assert.equal(h.calls.filter((c) => c.method === "Switch.Set").length, 2);
});
