"""Aggregate energy and estimated CO2 per Pacific day.

Avoided CO2 is ``load_lb`` (the load drawn straight from the grid at the time
it ran) minus ``used_lb`` (emissions attributed to the energy it actually
used). Grid energy passed through to the load counts at its own rate. Grid
energy that charges the battery adds its emissions to a pool carried across
days; solar adds none. Load drawn from the battery removes its proportional
share, so stored energy counts when used, not when charged. Rates use
WattTime actuals in lb/MWh; missing rates count toward Wh only.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Callable
from datetime import date, timedelta
from itertools import pairwise
from statistics import mean

from planner.adaptive import EFFICIENCY
from planner.telemetry import CAPACITY_WH

from solar_server.store import PLUG, SAMPLES, Store, day_key, day_keys

log = logging.getLogger(__name__)

# Nothing was recorded before this; the first update fills in every day since.
FIRST_DAY = "2026-10-01"
MAX_GAP = 3600  # Cap each integration interval at one hour.
RATE_GAP = 1800  # Carry each marginal rate for at most 30 minutes.
VERSION = 3  # Increment to recompute history from FIRST_DAY.

type Rate = Callable[[float], float | None]


def rate_lookup(samples: list[dict]) -> Rate:
    """Carry each actual rate from ``moer_t`` until the next, for at most RATE_GAP."""
    points = sorted(
        {
            int(s.get("moer_t", s["t"])): float(s["moer"])
            for s in samples
            if s.get("moer") is not None
        }.items()
    )
    times = [t for t, _ in points]

    def rate(t: float) -> float | None:
        i = bisect_right(times, t) - 1
        return points[i][1] if i >= 0 and t - times[i] <= RATE_GAP else None

    return rate


def covered_h(points: list[tuple[int, float]]) -> float:
    """Sum coverage hours, capping each gap at ``MAX_GAP`` seconds."""
    return sum(min(t1 - t0, MAX_GAP) for (t0, _), (t1, _) in pairwise(points)) / 3600


def integrate_wh(points: list[tuple[int, float]]) -> float:
    return energy(points, lambda _t: None)[0]


def energy(points: list[tuple[int, float]], rate: Rate) -> tuple[float, float]:
    """Integrate Wh and CO2 in lb, using interval-midpoint rates and capped gaps."""
    wh = lb = 0.0
    for (t0, w0), (t1, w1) in pairwise(points):
        seg = (w0 + w1) / 2 * min(t1 - t0, MAX_GAP) / 3600
        wh += seg
        r = rate((t0 + t1) / 2)
        if r is not None:
            lb += seg * r / 1e6
    return wh, lb


def cumulative(
    points: list[tuple[int, float]], rate: Rate
) -> Callable[[float], tuple[float, float]]:
    """Return cumulative Wh and CO2 in lb from the first point to a given time."""
    times = [t for t, _ in points]
    sums = [(0.0, 0.0)]
    for a, b in pairwise(points):
        wh, lb = energy([a, b], rate)
        sums.append((sums[-1][0] + wh, sums[-1][1] + lb))

    def at(t: float) -> tuple[float, float]:
        i = bisect_right(times, t) - 1
        if i < 0:
            return 0.0, 0.0
        if i >= len(points) - 1 or t <= times[i]:
            return sums[i]
        (t0, w0), (t1, w1) = points[i], points[i + 1]
        w = w0 + (w1 - w0) * (t - t0) / (t1 - t0)
        wh, lb = energy([(t0, w0), (int(t), w)], rate)
        return sums[i][0] + wh, sums[i][1] + lb

    return at


def load_co2(
    samples: list[dict], plug: list[dict], rate: Rate, stored_lb: float
) -> tuple[float, float, float, float]:
    """Estimate the load from the battery's energy balance and attribute its CO2.

    The Jackery's output reading lags and misses most draws, so the load is
    what came in (solar, and grid from the plug's meter) less what the charge
    gained. Charge readings are whole percent (31 Wh), so the balance runs
    between readings where the charge changes and spreads each span's load
    evenly over it. While the plug supplies power, the Jackery passes it to
    the load first and charges with the rest; that grid energy counts at its
    own rate. Battery energy carries the CO2 of the grid energy put in,
    including charging losses, and the load takes its share when drawn.

    Returns load Wh, its direct-grid CO2 baseline, CO2 attributed to it, and
    the CO2 left in the battery, all in lb except the Wh.
    """
    readings = [s for s in samples if s.get("battery_pct") is not None]
    if len(readings) < 2:
        return 0.0, 0.0, 0.0, stored_lb
    edges = [readings[0]]
    edges += [b for a, b in pairwise(readings) if b["battery_pct"] != a["battery_pct"]]
    if edges[-1] is not readings[-1]:
        edges.append(readings[-1])
    solar = cumulative(series(samples, "solar_w"), rate)
    grid_points = series(plug, "w")
    grid = cumulative(grid_points, rate)
    # Integrating 1 W while the plug draws power gives hours supplied.
    supplied = cumulative([(t, 1.0 if w > 0 else 0.0) for t, w in grid_points], rate)
    rates = [(s["t"], rate(s["t"])) for s in samples]
    load_wh = load_lb = used_lb = 0.0
    for a, b in pairwise(edges):
        t0, t1 = a["t"], b["t"]
        if t1 <= t0:
            continue
        solar_wh = solar(t1)[0] - solar(t0)[0]
        (g1, g1_lb), (g0, g0_lb) = grid(t1), grid(t0)
        grid_wh, grid_lb = g1 - g0, g1_lb - g0_lb
        share = min(1.0, (supplied(t1)[0] - supplied(t0)[0]) * 3600 / (t1 - t0))
        gained = (b["battery_pct"] - a["battery_pct"]) / 100 * CAPACITY_WH
        load = ((solar_wh + grid_wh) * EFFICIENCY - gained) / (
            share * EFFICIENCY + (1 - share) / EFFICIENCY
        )
        direct = load * share
        if direct > grid_wh:
            direct = grid_wh
            load = grid_wh + (solar_wh * EFFICIENCY - gained) * EFFICIENCY
        if load <= 0:
            # More charge than measured input, usually from a low solar reading.
            load = direct = 0.0
        direct_lb = grid_lb * direct / grid_wh if grid_wh > 0 else 0.0
        stored_lb += grid_lb - direct_lb
        drawn = (load - direct) / EFFICIENCY
        held = b["battery_pct"] / 100 * CAPACITY_WH + drawn
        take = stored_lb * min(1.0, drawn / held) if held > 0 else stored_lb
        stored_lb -= take
        load_wh += load
        used_lb += direct_lb + take
        power = load / (t1 - t0)  # Wh per second
        span = [(t, r) for t, r in rates if t0 <= t <= t1]
        load_lb += sum(
            power * (u - t) * r / 1e6 for (t, r), (u, _) in pairwise(span) if r is not None
        )
    return load_wh, load_lb, used_lb, stored_lb


def series(items: list[dict], key: str) -> list[tuple[int, float]]:
    return [(int(i["t"]), float(i[key])) for i in items if i.get(key) is not None]


def day_totals(store: Store, day: str, stored_lb: float | None = None) -> dict | None:
    """Compute daily totals from initial battery emissions in ``stored_lb``.

    If omitted, price the first battery level at the day's mean rate; an
    unknown charge never counts as clean.
    """
    samples = sorted(store.day(SAMPLES, day), key=lambda s: s["t"])
    plug = sorted(store.day(PLUG, day), key=lambda r: r["t"])
    if not samples and not plug:
        return None
    rate = rate_lookup(samples)
    if stored_lb is None:
        first = next((s for s in samples if s.get("battery_pct") is not None), None)
        moers = [float(s["moer"]) for s in samples if s.get("moer") is not None]
        r = mean(moers) if moers else 0.0
        stored_lb = first["battery_pct"] / 100 * CAPACITY_WH * r / 1e6 if first else 0.0

    solar = series(samples, "solar_w")
    grid = series(plug, "w")
    grid_wh, grid_lb = energy(grid, rate)
    load_wh, load_lb, used_lb, stored_lb = load_co2(samples, plug, rate, stored_lb)
    # Plug draw before the first or after the last change in charge goes into the battery.
    by = cumulative(grid, rate)
    readings = [s["t"] for s in samples if s.get("battery_pct") is not None]
    if len(readings) >= 2:
        stored_lb += by(readings[0])[1] + grid_lb - by(readings[-1])[1]
    else:
        stored_lb += grid_lb
    peaks = [float(s["battery_pct"]) for s in samples if s.get("battery_pct") is not None]
    return {
        "day": day,
        "solar_wh": round(integrate_wh(solar), 1),
        "solar_n": len(solar),
        "solar_h": round(covered_h(solar), 2),
        "load_wh": round(load_wh, 1),
        "grid_wh": round(grid_wh, 1),
        "load_lb": round(load_lb, 4),
        "grid_lb": round(grid_lb, 4),
        "used_lb": round(used_lb, 4),
        "stored_lb": round(stored_lb, 6),
        "battery_peak_pct": max(peaks) if peaks else None,
    }


def update(store: Store, now: int) -> list[str]:
    """Recompute every day from the last one updated through today.

    Normally that's just today, plus yesterday right after midnight. The first
    run, and the first after the collector has been down, fill in the gap.
    """
    state = store.get_state("totals") or {}
    last = state.get("day", FIRST_DAY) if state.get("v") == VERSION else FIRST_DAY
    today = day_key(now)
    days = _days_from(last, today)
    # Pick up the battery's CO2 from the latest day before these.
    before = store.totals(_days_from(FIRST_DAY, days[0])[-8:-1]) if days[0] > FIRST_DAY else []
    stored_lb = before[-1].get("stored_lb") if before else None
    for day in days:
        totals = day_totals(store, day, stored_lb)
        if totals is not None:
            store.put_total(day, totals)
            stored_lb = totals["stored_lb"]
    store.put_state("totals", {"day": today, "v": VERSION})
    return days


def _days_from(first: str, last: str) -> list[str]:
    d, end = date.fromisoformat(first), date.fromisoformat(last)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def read(store: Store, since: int, until: int) -> list[dict]:
    """Read stored daily totals for the range, omitting days without data."""
    return store.totals(day_keys(since, until))
