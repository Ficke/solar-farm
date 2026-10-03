#!/usr/bin/env node
// Dry run of the plug: what grid-gate.js would do over the next 24 hours
// with the published plan, minute by minute, without any hardware.
//
//   node device/sim.js                          # fetches the live plan.json
//   node device/sim.js path/to/plan.json        # or a local file
//   node device/sim.js --stale                  # pretend the plan is stale (fallback rules)
"use strict";

const fs = require("node:fs");
const { load } = require("./test/harness");

const PLAN_URL = "https://ficke.github.io/solar-farm/plan.json";
const fmt = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Los_Angeles",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23"
});

function localMinutes(unix) {
  const parts = Object.fromEntries(fmt.formatToParts(new Date(unix * 1000)).map((p) => [p.type, p.value]));
  return Number(parts.hour) * 60 + Number(parts.minute);
}

async function getPlan(arg) {
  if (arg && !arg.startsWith("--")) return JSON.parse(fs.readFileSync(arg, "utf8"));
  const res = await fetch(PLAN_URL + "?t=" + Date.now());
  if (!res.ok) throw new Error(`plan fetch failed: ${res.status}`);
  return res.json();
}

async function main() {
  const args = process.argv.slice(2);
  const plan = await getPlan(args.find((a) => !a.startsWith("--")));
  const stale = args.includes("--stale");
  const { context } = load();
  const start = Math.floor(Date.now() / 60000) * 60;
  const s = {
    plan: stale ? null : plan,
    index: null,
    indexAt: 0,
    lastOnAt: start,
    safetyUntil: 0,
    on: false
  };

  console.log(`Plan generated ${fmt.format(new Date(plan.generated_at * 1000))} Pacific` + (stale ? " (ignored: --stale)" : ""));
  let prev = null;
  let onMinutes = 0;
  for (let t = start; t < start + 24 * 3600; t += 60) {
    // Plans go stale after 3 h; the real planner refreshes every 30 min, so keep it fresh here.
    if (s.plan) s.plan = Object.assign({}, plan, { generated_at: t - 60 });
    const d = context.decide(s, t, localMinutes(t), context.CFG);
    if (d.reason === "safety" && !(s.safetyUntil > t)) s.safetyUntil = t + context.CFG.safetyHold;
    if (d.on) {
      s.lastOnAt = t;
      onMinutes++;
    }
    s.on = d.on;
    const key = `${d.on}/${d.reason}`;
    if (key !== prev) {
      console.log(`  ${fmt.format(new Date(t * 1000))}  grid ${d.on ? "ON " : "off"}  (${d.reason})`);
      prev = key;
    }
  }
  console.log(`Grid on for ${(onMinutes / 60).toFixed(1)} h in the next 24 h.`);
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
