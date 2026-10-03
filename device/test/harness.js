// Loads grid-gate.js into a sandbox with a fake Shelly runtime so its
// functions can be exercised under Node.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "..", "src", "grid-gate.js"), "utf8");

function load(opts = {}) {
  const calls = [];
  const timers = [];
  const endpoints = {};
  const device = {
    sys: { unixtime: opts.unixtime ?? 1790000000, time: opts.time ?? "12:00" },
    sw: { output: opts.output ?? false, apower: 0, aenergy: { total: opts.energy ?? 0 } },
    kvs: opts.kvs ?? {},
    responses: opts.responses ?? {}
  };

  const Shelly = {
    call(method, params, cb) {
      calls.push({ method, params });
      if (method === "KVS.GetMany") {
        const items = Object.entries(device.kvs).map(([key, value]) => ({ key, value }));
        if (cb) cb({ items }, 0, "");
        return;
      }
      if (method === "Switch.Set") {
        device.sw.output = params.on;
      }
      const r = device.responses[method];
      if (cb && r) cb(typeof r === "function" ? r(params) : r, 0, "");
    },
    getComponentStatus(name) {
      if (name === "sys") return device.sys;
      if (name === "switch:0") return device.sw;
      return null;
    }
  };

  const context = {
    Shelly,
    Timer: { set: (ms, repeat, fn) => timers.push({ ms, repeat, fn }) },
    HTTPServer: { registerEndpoint: (name, fn) => (endpoints[name] = fn) },
    print: () => {},
    JSON,
    Math,
    parseInt,
    isNaN
  };
  vm.createContext(context);
  vm.runInContext(SOURCE, context, { filename: "grid-gate.js" });
  return { context, calls, timers, endpoints, device };
}

module.exports = { load, SOURCE };
