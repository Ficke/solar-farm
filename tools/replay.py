"""Replay the charging engine over recorded forecasts, readings and emission rates.

The server's own planner runs every minute against a simulated battery. Solar,
load and live emission rates come from the recording; the battery level, plug
state and grid draw come from the simulation, so a different plan plays out
as it would have. Scores grid energy, dirty grid energy (over 300 lb/MWh),
CO2, relay changes and the 4 pm shortfall per day, 4 pm to 4 pm.

    just replay fetch DATA --since 2026-10-04
    just replay run DATA --start 2026-10-12 --end 2026-11-07

``fetch`` reads production Firestore over REST. It sends a bearer token from
``gcloud auth print-access-token`` when gcloud is signed in, else none (an
agent proxy that adds credentials).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import urllib.error
import urllib.request
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from planner.battery import AC_CHARGE, DISCHARGE, Battery, load_points
from planner.plan import PACIFIC
from solar_server import tasks
from solar_server.config import Settings
from solar_server.store import PLUG, SAMPLES, MemoryStore

FIRESTORE = (
    "https://firestore.googleapis.com/v1/projects/solar-farm-510518/databases/(default)/documents/"
)
SERIES = ("samples", "plug", "forecasts")
CLEAN = 300  # lb/MWh; actual rates sit near 0 or above 800.
LIVE_DELAY = 60  # Seconds before a WattTime actual reaches the server.
FORECAST_MAX_AGE = 7200  # The server replans from a cached forecast this long.
PEAK = (16, 21)
LOW_ON, LOW_OFF = 10, 15  # Plug script's low-battery peak override, percent.
BRIDGE = 180  # Plug script stays on if a window starts within this many seconds.


def fetch(data: Path, since: date, until: date) -> None:
    """Save each series' daily documents and the battery model as JSON."""
    data.mkdir(parents=True, exist_ok=True)
    token = _token()
    day = since
    while day <= until:
        for series in SERIES:
            doc = _get(f"{series}/{day.isoformat()}", token)
            if doc is not None:
                (data / f"{series}-{day.isoformat()}.json").write_text(
                    json.dumps(doc.get("items", []))
                )
        day += timedelta(days=1)
    battery = _get("state/battery", token) or {}
    (data / "battery.json").write_text(battery.get("data_json", "{}"))


def _token() -> str | None:
    if not shutil.which("gcloud"):
        return None
    out = subprocess.run(
        ["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip() or None


def _get(path: str, token: str | None) -> dict | None:
    request = urllib.request.Request(FIRESTORE + path)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return {k: _value(v) for k, v in body.get("fields", {}).items()}


def _value(v: dict):
    kind, x = next(iter(v.items()))
    if kind == "integerValue":
        return int(x)
    if kind == "doubleValue":
        return float(x)
    if kind == "nullValue":
        return None
    if kind == "arrayValue":
        return [_value(i) for i in x.get("values", [])]
    if kind == "mapValue":
        return {k: _value(i) for k, i in x.get("fields", {}).items()}
    return x


def load(data: Path) -> dict:
    out: dict = {s: [] for s in SERIES}
    for series in SERIES:
        for f in sorted(data.glob(f"{series}-*.json")):
            out[series] += json.loads(f.read_text())
        out[series].sort(key=lambda i: i["t"])
    battery = data / "battery.json"
    out["battery"] = json.loads(battery.read_text()).get("battery") if battery.exists() else None
    return out


class Steps[V]:
    """Look up the latest value at or before a time."""

    def __init__(self, points: list[tuple[int, V]]) -> None:
        self.times = [t for t, _ in points]
        self.values = [v for _, v in points]

    def at(self, t: float, max_age: float = math.inf) -> tuple[int, V] | None:
        i = bisect_right(self.times, t) - 1
        if i < 0 or t - self.times[i] > max_age:
            return None
        return self.times[i], self.values[i]


def replay(rec: dict, start: int, end: int, settings: Settings, trace: bool = False) -> list[dict]:
    """Run the planner every minute from ``start`` to ``end``; return per-day scores."""
    battery = Battery.from_dict(rec["battery"])
    samples, plug = rec["samples"], rec["plug"]
    store = MemoryStore()
    # Readings before the start train the solar profile and charge rate.
    for s in samples:
        if start - 8 * 86400 <= s["t"] < start:
            store.append(SAMPLES, s)
    for r in plug:
        if start - 8 * 86400 <= r["t"] < start:
            store.append(PLUG, r)
    capacity = battery.capacity_wh
    load = Steps(load_points(samples, plug, battery))
    solar = Steps([(s["t"], s["solar_w"]) for s in samples if s.get("solar_w") is not None])
    rate = Steps(sorted({s["moer_t"]: s["moer"] for s in samples if s.get("moer_t")}.items()))
    forecasts = Steps([(f["t"], f) for f in rec["forecasts"]])
    first = next(s for s in samples if s["t"] >= start and s.get("battery_pct") is not None)
    level = battery.wh(first["battery_pct"])
    on = low = False
    days: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for t in range(start, end, 60):
        now = datetime.fromtimestamp(t, UTC)
        local = now.astimezone(PACIFIC)
        pct = math.floor(level / capacity * 100 + 1e-9)
        live = rate.at(t - LIVE_DELAY, 900)
        sample = {
            "t": t,
            "battery_pct": float(pct),
            "solar_w": (solar.at(t, 900) or (0, 0.0))[1],
            "output_w": 0.0,
            "ac_input_w": 0.0,
        }
        if live:
            sample |= {"moer_t": live[0], "moer": live[1]}
        store.put_state("sample", {"sample": sample})
        # Production's measured battery, kept fresh so the planner doesn't remeasure.
        store.put_state("battery", {"t": t, "battery": battery.to_dict()})
        if t % 300 == 0:
            store.append(SAMPLES, sample)
        archive = forecasts.at(t, FORECAST_MAX_AGE)
        plan = None
        if archive:
            a = archive[1]
            points = tasks.clean_forecast(
                [
                    (datetime.fromtimestamp(a["start"] + i * a["step"], UTC), float(v))
                    for i, v in enumerate(a["values"])
                    if v is not None
                ]
            )
            if any(p >= now for p, _ in points):
                plan = tasks.charging_plan(
                    store, tasks.rate_timeline(store, points, now), settings, now
                )
                store.put_state("plan", plan)
        # The plug script's rules, in order: peak, then the plan.
        was = on
        if PEAK[0] <= local.hour < PEAK[1]:
            low = pct < LOW_OFF if low else pct <= LOW_ON
            on = low
        else:
            low = False
            windows = (plan or store.get_state("plan") or {}).get("windows", [])
            inside = any(s <= t < e for s, e in windows)
            on = inside or (on and any(s <= t + BRIDGE < e for s, e in windows))
        # One minute of energy flow: the plug runs the load and charges.
        load_w = (load.at(t, 3600) or (0, 0.0))[1]
        solar_wh = sample["solar_w"] * battery.solar_stored / 60
        day = days[(local + timedelta(hours=8)).date().isoformat()]  # 4 pm to 4 pm, by end
        if on:
            room = max(0.0, capacity - level - solar_wh)
            charge = min(settings.charge_w * AC_CHARGE / 60, room)
            level += charge + solar_wh
            wall = charge / AC_CHARGE + load_w / 60
        else:
            level += solar_wh - load_w / DISCHARGE / 60
            wall = 0.0
        level = min(capacity, max(0.0, level))
        actual = rate.at(t, 900)
        moer = actual[1] if actual else 0.0
        if trace and on != was:
            print(f"{local:%m-%d %H:%M} {'on ' if on else 'off'} {pct:3d}% rate {moer:5.0f}")
        day["grid_wh"] += wall
        day["co2_lb"] += wall * moer / 1e6
        day["dirty_wh"] += wall if moer > CLEAN else 0.0
        day["changes"] += on != was
        day["min_pct"] = min(day.get("min_pct", 100.0), level / capacity * 100)
        if local.time() == time(15, 59) and plan:  # the level at 4 pm
            day["pct_4pm"] = level / capacity * 100
            day["miss_wh"] = max(0.0, plan["target_pct"] / 100 * capacity - level)
    return [{"day": d, **v} for d, v in sorted(days.items())]


def report(rows: list[dict]) -> None:
    print("day         grid kWh  dirty kWh  CO2 kg  changes  4pm %  short Wh  min %")
    total: dict[str, float] = defaultdict(float)
    for r in rows:
        print(
            f"{r['day']}  {r['grid_wh'] / 1000:8.2f}  {r['dirty_wh'] / 1000:9.2f}"
            f"  {r['co2_lb'] * 0.4536:6.2f}  {r['changes']:7.0f}  {r.get('pct_4pm', 0):5.1f}"
            f"  {r.get('miss_wh', 0):8.0f}  {r['min_pct']:5.1f}"
        )
        for k in ("grid_wh", "dirty_wh", "co2_lb", "changes", "miss_wh"):
            total[k] += r.get(k, 0)
        total["misses"] += r.get("miss_wh", 0) > 100
        total["floor"] += r["min_pct"] < 19
    print(
        f"total       {total['grid_wh'] / 1000:8.2f}  {total['dirty_wh'] / 1000:9.2f}"
        f"  {total['co2_lb'] * 0.4536:6.2f}  {total['changes']:7.0f}"
        f"         {total['miss_wh']:8.0f}"
    )
    print(f"days short at 4 pm by over 100 Wh: {total['misses']:.0f}")
    print(f"days below 19%: {total['floor']:.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="save production data to a folder")
    f.add_argument("data", type=Path)
    f.add_argument("--since", type=date.fromisoformat, required=True)
    f.add_argument("--until", type=date.fromisoformat, default=date.today())
    r = sub.add_parser("run", help="replay the planner over a saved folder")
    r.add_argument("data", type=Path)
    r.add_argument("--start", type=date.fromisoformat, required=True)
    r.add_argument("--end", type=date.fromisoformat, required=True)
    r.add_argument("--json", type=Path, help="also write per-day scores here")
    r.add_argument("--trace", action="store_true", help="print each relay change")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.data, args.since, args.until)
        return
    # Days run 4 pm to 4 pm, the planner's deadline to deadline.
    start = int(datetime.combine(args.start, time(16), PACIFIC).timestamp())
    end = int(datetime.combine(args.end, time(16), PACIFIC).timestamp())
    rows = replay(load(args.data), start, end, Settings(), args.trace)
    report(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
