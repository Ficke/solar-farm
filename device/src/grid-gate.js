// Control AC access to the Jackery, blocking peak hours before applying plans
// or safety, live-index and daytime fallbacks. See README.md for rule order.
// Keep ES5 syntax and named top-level callbacks for Shelly runtime compatibility.

// Peak and fallback bounds use local minutes after midnight; durations use seconds.
var CFG = {
  planUrl: "",
  plugKey: "",
  reportUrl: "",
  wtAuth: "", // Deploy stores base64-encoded "user:password" for WattTime login.
  region: "CAISO_NORTH",
  threshold: 25, // Turn on at or below this WattTime percentile.
  hysteresis: 5, // Stay on until the index exceeds threshold plus hysteresis.
  peakStart: 960,
  peakEnd: 1260,
  fallbackStart: 600,
  fallbackEnd: 900,
  planMaxAge: 10800,
  indexMaxAge: 900,
  safetyOffMax: 108000,
  safetyHold: 7200,
  bridge: 180,
  // During peak, grid may carry the load once the battery is nearly empty.
  lowOn: 10, // Battery percent at or below which peak power is allowed.
  lowOff: 15, // Battery percent at which peak power stops again.
  lowMaxAge: 600, // Maximum battery reading age in seconds.
  lowHold: 180 // Firmware turns the relay back off if the script stops renewing it.
};

var S = {
  plan: null,
  planAt: 0,
  index: null,
  indexAt: 0,
  token: "",
  tokenAt: 0,
  lastOnAt: 0,
  safetyUntil: 0,
  on: false,
  reason: "start",
  sessionStart: 0,
  sessionStartWh: 0,
  sessions: [],
  ticks: 0,
  lastSavedOnAt: 0
};

function inWindows(windows, now) {
  if (!windows) return false;
  for (var i = 0; i < windows.length; i++) {
    if (now >= windows[i][0] && now < windows[i][1]) return true;
  }
  return false;
}

// Bridge short gaps only while on to avoid relay cycling during replans.
function planOn(s, now, cfg) {
  var w = s.plan.windows;
  return inWindows(w, now) || (s.on === true && inWindows(w, now + cfg.bridge));
}

// The server's battery reading arrives with each plan and lags the battery
// by a few minutes, so the exception overshoots lowOff slightly.
function batteryLow(s, now, cfg) {
  var p = s.plan;
  if (!p || typeof p.battery_pct !== "number" || typeof p.battery_at !== "number") return false;
  if (now - p.battery_at > cfg.lowMaxAge || p.battery_at - now > 60) return false;
  if (s.reason === "peak-low") return p.battery_pct < cfg.lowOff;
  return p.battery_pct <= cfg.lowOn;
}

function decide(s, now, localMin, cfg) {
  if (localMin < 0) return { on: false, reason: "no-time" };
  if (localMin >= cfg.peakStart && localMin < cfg.peakEnd) {
    if (batteryLow(s, now, cfg)) return { on: true, reason: "peak-low" };
    return { on: false, reason: "peak" };
  }
  // Healthy solar-only operation can exceed 30 hours without grid power.
  // Only a recent, feasible battery-aware plan may suppress the time backstop.
  if (s.plan && s.plan.strategy === "adaptive" && s.plan.shortfall_wh === 0 &&
      now - s.plan.generated_at >= 0 && now - s.plan.generated_at < 900) {
    return { on: planOn(s, now, cfg), reason: "plan" };
  }
  if (s.safetyUntil > now || (s.lastOnAt > 0 && now - s.lastOnAt > cfg.safetyOffMax)) {
    return { on: true, reason: "safety" };
  }
  if (s.plan && now - s.plan.generated_at < cfg.planMaxAge) {
    return { on: planOn(s, now, cfg), reason: "plan" };
  }
  if (s.index !== null && now - s.indexAt < cfg.indexMaxAge) {
    var limit = s.on ? cfg.threshold + cfg.hysteresis : cfg.threshold;
    return { on: s.index <= limit, reason: "index" };
  }
  return {
    on: localMin >= cfg.fallbackStart && localMin < cfg.fallbackEnd,
    reason: "fallback"
  };
}

function parseLocalMinutes(hhmm) {
  if (typeof hhmm !== "string" || hhmm.length < 4) return -1;
  var parts = hhmm.split(":");
  if (parts.length < 2) return -1;
  var h = parseInt(parts[0], 10);
  var m = parseInt(parts[1], 10);
  if (isNaN(h) || isNaN(m)) return -1;
  return h * 60 + m;
}

function validPlan(p) {
  if (!p || typeof p.generated_at !== "number" || !p.windows) return false;
  for (var i = 0; i < p.windows.length; i++) {
    var w = p.windows[i];
    if (!w || w.length !== 2 || typeof w[0] !== "number" || typeof w[1] !== "number") {
      return false;
    }
  }
  return true;
}

function nowUnix() {
  var sys = Shelly.getComponentStatus("sys");
  return sys && sys.unixtime ? sys.unixtime : 0;
}

function localMinutes() {
  var sys = Shelly.getComponentStatus("sys");
  return sys ? parseLocalMinutes(sys.time) : -1;
}

function switchEnergyWh() {
  var sw = Shelly.getComponentStatus("switch:0");
  return sw && sw.aenergy ? sw.aenergy.total : 0;
}

function recordTransition(on, now) {
  if (on) {
    S.sessionStart = now;
    S.sessionStartWh = switchEnergyWh();
    return;
  }
  if (S.sessionStart > 0) {
    S.sessions.push({
      start: S.sessionStart,
      end: now,
      wh: Math.round(switchEnergyWh() - S.sessionStartWh)
    });
    if (S.sessions.length > 14) S.sessions.splice(0, S.sessions.length - 14);
  }
  S.sessionStart = 0;
}

function saveLastOn(now) {
  if (now - S.lastSavedOnAt < 1800) return;
  S.lastSavedOnAt = now;
  Shelly.call("KVS.Set", { key: "gg.last_on", value: JSON.stringify(now) });
}

function applyDecision(d, now) {
  if (d.reason === "safety" && !(S.safetyUntil > now)) {
    S.safetyUntil = now + CFG.safetyHold;
  }
  if (d.reason === "peak-low") {
    // Renew the flip-back timer every tick so peak power ends if the script stops.
    Shelly.call("Switch.Set", { id: 0, on: true, toggle_after: CFG.lowHold });
  } else if (d.on !== S.on || S.reason === "peak-low") {
    // A plain set also cancels a pending flip-back timer.
    Shelly.call("Switch.Set", { id: 0, on: d.on });
  }
  if (d.on !== S.on) {
    recordTransition(d.on, now);
    print("grid-gate: grid " + (d.on ? "on" : "off") + " (" + d.reason + ")");
  }
  S.on = d.on;
  S.reason = d.reason;
  if (d.on) {
    S.lastOnAt = now;
    saveLastOn(now);
  }
}

function acceptPlan(body) {
  var p = null;
  try {
    p = JSON.parse(body);
  } catch (e) {
    print("grid-gate: plan is not JSON");
    return;
  }
  if (validPlan(p)) {
    S.plan = p;
    S.planAt = nowUnix();
  }
}

function onPlan(res, errCode, errMsg) {
  if (errCode !== 0 || !res || res.code !== 200) {
    print("grid-gate: plan fetch failed " + errCode + " " + errMsg);
    return;
  }
  acceptPlan(res.body);
}

function fetchPlan(now) {
  if (!CFG.planUrl) return;
  if (!CFG.plugKey) {
    Shelly.call("HTTP.GET", { url: CFG.planUrl + "?t=" + now, timeout: 10 }, onPlan);
    return;
  }
  Shelly.call(
    "HTTP.Request",
    {
      method: "GET",
      url: CFG.planUrl,
      headers: { "X-Plug-Key": CFG.plugKey },
      timeout: 10
    },
    onPlan
  );
}

function reportBody(now) {
  var sw = Shelly.getComponentStatus("switch:0");
  return JSON.stringify({
    t: now,
    on: S.on,
    reason: S.reason,
    w: sw && typeof sw.apower === "number" ? sw.apower : null,
    wh: sw && sw.aenergy ? sw.aenergy.total : null,
    index: S.index,
    plan_at: S.plan ? S.plan.generated_at : null
  });
}

// Reports return the current plan (200), or no content (204) before one exists.
function onReport(res, errCode) {
  if (errCode !== 0 || !res || (res.code !== 200 && res.code !== 204)) {
    print("grid-gate: report failed " + errCode);
    return;
  }
  if (res.code === 200) acceptPlan(res.body);
}

function sendReport(now) {
  if (!CFG.reportUrl || !CFG.plugKey) return;
  Shelly.call(
    "HTTP.Request",
    {
      method: "POST",
      url: CFG.reportUrl + "?plan=1",
      headers: { "X-Plug-Key": CFG.plugKey, "Content-Type": "application/json" },
      body: reportBody(now),
      timeout: 10
    },
    onReport
  );
}

function onIndex(res, errCode) {
  if (errCode !== 0 || !res) return;
  if (res.code === 401 || res.code === 403) {
    S.token = "";
    return;
  }
  if (res.code !== 200) return;
  try {
    var body = JSON.parse(res.body);
    if (body.data && body.data.length > 0) {
      S.index = body.data[0].value;
      S.indexAt = nowUnix();
    }
  } catch (e) {
    print("grid-gate: index is not JSON");
  }
}

function requestIndex() {
  Shelly.call(
    "HTTP.Request",
    {
      method: "GET",
      url: "https://api.watttime.org/v3/signal-index?region=" + CFG.region + "&signal_type=co2_moer",
      headers: { Authorization: "Bearer " + S.token },
      timeout: 10
    },
    onIndex
  );
}

function onLogin(res, errCode) {
  if (errCode !== 0 || !res || res.code !== 200) return;
  try {
    S.token = JSON.parse(res.body).token;
    S.tokenAt = nowUnix();
    requestIndex();
  } catch (e) {
    print("grid-gate: login response is not JSON");
  }
}

function fetchIndex(now) {
  if (!CFG.wtAuth) return;
  if (S.token && now - S.tokenAt < 1500) {
    requestIndex();
    return;
  }
  Shelly.call(
    "HTTP.Request",
    {
      method: "GET",
      url: "https://api.watttime.org/login",
      headers: { Authorization: "Basic " + CFG.wtAuth },
      timeout: 10
    },
    onLogin
  );
}

function planIsFresh(now) {
  return S.plan !== null && now - S.plan.generated_at < CFG.planMaxAge;
}

function tick() {
  var now = nowUnix();
  if (now > 0) {
    // Reports bring the plan back every minute; fetch it only when they don't.
    if (S.ticks % 10 === 0 && now - S.planAt >= 300) fetchPlan(now);
    // Reserve one of Shelly's two concurrent call slots for the report.
    else if (S.ticks % 5 === 0 && !planIsFresh(now)) fetchIndex(now);
    if (S.lastOnAt === 0) S.lastOnAt = now; // Start the safety clock on first boot.
  }
  S.ticks++;
  var sw = Shelly.getComponentStatus("switch:0");
  if (sw && typeof sw.output === "boolean") S.on = sw.output;
  applyDecision(decide(S, now, now > 0 ? localMinutes() : -1, CFG), now);
  if (now > 0) sendReport(now);
}

function onStatusRequest(request, response) {
  response.code = 200;
  response.headers = [["Content-Type", "application/json"]];
  response.body = JSON.stringify({
    on: S.on,
    reason: S.reason,
    planGeneratedAt: S.plan ? S.plan.generated_at : null,
    planWindows: S.plan ? S.plan.windows : [],
    index: S.index,
    indexAt: S.indexAt,
    lastOnAt: S.lastOnAt,
    safetyUntil: S.safetyUntil,
    sessions: S.sessions
  });
  response.send();
}

// KVS.GetMany returns items as an object keyed by name on older firmware and
// as an array of {key, value} on newer firmware.
function kvsItems(res) {
  var out = {};
  if (!res || !res.items) return out;
  var items = res.items;
  if (items.length !== undefined) {
    for (var i = 0; i < items.length; i++) out[items[i].key] = items[i].value;
  } else {
    for (var k in items) out[k] = items[k].value;
  }
  return out;
}

function applyConfig(kv) {
  if (kv["gg.plan_url"]) CFG.planUrl = kv["gg.plan_url"];
  if (kv["gg.wt_auth"]) CFG.wtAuth = kv["gg.wt_auth"];
  if (kv["gg.plug_key"]) CFG.plugKey = kv["gg.plug_key"];
  if (kv["gg.report_url"]) CFG.reportUrl = kv["gg.report_url"];
  if (kv["gg.cfg"]) {
    try {
      var extra = JSON.parse(kv["gg.cfg"]);
      for (var key in extra) {
        if (CFG[key] !== undefined) CFG[key] = extra[key];
      }
    } catch (e) {
      print("grid-gate: gg.cfg is not JSON");
    }
  }
  if (kv["gg.last_on"]) S.lastOnAt = JSON.parse(kv["gg.last_on"]);
}

function onConfig(res) {
  applyConfig(kvsItems(res));
  var sw = Shelly.getComponentStatus("switch:0");
  S.on = sw ? sw.output === true : false;
  if (S.on) recordTransition(true, nowUnix());
  HTTPServer.registerEndpoint("status", onStatusRequest);
  tick();
  Timer.set(60000, true, tick);
}

Shelly.call("KVS.GetMany", { match: "gg.*" }, onConfig);
