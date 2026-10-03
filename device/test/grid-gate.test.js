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
    lastOnAt: NOW - 20 * 3600
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

test("18 hours off forces the grid on, but not during peak", () => {
  const { context } = load();
  const s = freshState(context, {
    plan: { generated_at: NOW - 60, windows: [] },
    lastOnAt: NOW - 18 * 3600 - 1
  });
  assert.deepEqual({ ...context.decide(s, NOW, 23 * 60, context.CFG) }, { on: true, reason: "safety" });
  assert.equal(context.decide(s, NOW, 17 * 60, context.CFG).reason, "peak");
});

test("unknown time keeps the grid off", () => {
  const { context } = load();
  assert.equal(context.parseLocalMinutes(null), -1);
  assert.deepEqual({ ...context.decide(freshState(context), NOW, -1, context.CFG) }, { on: false, reason: "no-time" });
});

test("startup reads config from KVS, follows the plan and logs a charge session", () => {
  const plan = { generated_at: NOW - 60, windows: [[NOW - 60, NOW + 60]] };
  const h = load({
    time: "11:00",
    kvs: {
      "gg.plan_url": "https://example.github.io/solar-farm/plan.json",
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
