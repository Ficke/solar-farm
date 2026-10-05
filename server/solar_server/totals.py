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
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from planner.battery import AC_CHARGE, DISCHARGE, Battery

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


@dataclass
class Pool:
    """Emissions carried by the energy in the battery.

    ``unknown_wh`` is charge of unknown origin, present when readings began.
    The load drawing it counts as if it ran from the grid at that moment, so
    it neither adds nor avoids CO2.
    """

    stored_lb: float = 0.0
    unknown_wh: float = 0.0


def load_co2(
    samples: list[dict], plug: list[dict], rate: Rate, pool: Pool, battery: Battery
) -> tuple[float, float, float]:
    """Estimate the load from the battery's energy balance and attribute its CO2.

    The Jackery's output reading lags and misses most draws, so the load is
    what came in (solar, and grid from the plug's meter) less what the charge
    gained. Charge readings are whole percent (about 31 Wh), so the balance runs
    between readings where the charge changes and spreads each span's load
    evenly over it. While the plug supplies power, the Jackery passes it to
    the load first and charges with the rest; that grid energy counts at its
    own rate. Pool energy carries the CO2 of the grid energy put in,
    including charging losses, and the load takes its share when drawn.

    Returns load Wh, its direct-grid CO2 baseline in lb, and the CO2 in lb
    attributed to it; updates ``pool``.
    """
    readings = [s for s in samples if s.get("battery_pct") is not None]
    if len(readings) < 2:
        return 0.0, 0.0, 0.0
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
        gained = battery.wh(b["battery_pct"] - a["battery_pct"])
        solar_in = solar_wh * battery.solar_stored
        load = (solar_in + grid_wh * AC_CHARGE - gained) / (
            share * AC_CHARGE + (1 - share) / DISCHARGE
        )
        direct = load * share
        if direct > grid_wh:
            direct = grid_wh
            load = grid_wh + (solar_in - gained) * DISCHARGE
        if load <= 0:
            # More charge than measured input, usually from a low solar reading.
            load = direct = 0.0
        power = load / (t1 - t0)  # Wh per second
        span = [(t, r) for t, r in rates if t0 <= t <= t1]
        baseline_lb = sum(
            power * (u - t) * r / 1e6 for (t, r), (u, _) in pairwise(span) if r is not None
        )
        direct_lb = grid_lb * direct / grid_wh if grid_wh > 0 else 0.0
        pool.stored_lb += grid_lb - direct_lb
        drawn = (load - direct) / DISCHARGE
        held = battery.wh(b["battery_pct"]) + drawn
        unknown = min(1.0, pool.unknown_wh / held) if held > 0 else 1.0
        known = held - pool.unknown_wh
        take = pool.stored_lb * min(1.0, drawn * (1 - unknown) / known) if known > 0 else 0.0
        pool.stored_lb -= take
        pool.unknown_wh = max(0.0, pool.unknown_wh - drawn * unknown)
        neutral_lb = baseline_lb * (load - direct) * unknown / load if load > 0 else 0.0
        load_wh += load
        load_lb += baseline_lb
        used_lb += direct_lb + take + neutral_lb
    return load_wh, load_lb, used_lb


def series(items: list[dict], key: str) -> list[tuple[int, float]]:
    return [(int(i["t"]), float(i[key])) for i in items if i.get(key) is not None]


def day_totals(
    store: Store, day: str, pool: Pool | None = None, battery: Battery | None = None
) -> dict | None:
    """Compute daily totals, starting from the previous day's ``pool``.

    Without one, the first charge reading is of unknown origin. ``battery``
    gives the measured capacity and solar scale; solar Wh are scaled to the
    panel's output.
    """
    battery = battery or Battery()
    samples = sorted(store.day(SAMPLES, day), key=lambda s: s["t"])
    plug = sorted(store.day(PLUG, day), key=lambda r: r["t"])
    if not samples and not plug:
        return None
    rate = rate_lookup(samples)
    if pool is None:
        first = next((s for s in samples if s.get("battery_pct") is not None), None)
        pool = Pool(unknown_wh=battery.wh(first["battery_pct"]) if first else 0.0)

    solar = series(samples, "solar_w")
    grid = series(plug, "w")
    grid_wh, grid_lb = energy(grid, rate)
    load_wh, load_lb, used_lb = load_co2(samples, plug, rate, pool, battery)
    # Plug draw before the first or after the last change in charge goes into the battery.
    by = cumulative(grid, rate)
    readings = [s["t"] for s in samples if s.get("battery_pct") is not None]
    if len(readings) >= 2:
        pool.stored_lb += by(readings[0])[1] + grid_lb - by(readings[-1])[1]
    else:
        pool.stored_lb += grid_lb
    peaks = [float(s["battery_pct"]) for s in samples if s.get("battery_pct") is not None]
    return {
        "day": day,
        "solar_wh": round(integrate_wh(solar) * battery.solar_scale, 1),
        "solar_n": len(solar),
        "solar_h": round(covered_h(solar), 2),
        "load_wh": round(load_wh, 1),
        "grid_wh": round(grid_wh, 1),
        "load_lb": round(load_lb, 4),
        "grid_lb": round(grid_lb, 4),
        "used_lb": round(used_lb, 4),
        "stored_lb": round(pool.stored_lb, 6),
        "unknown_wh": round(pool.unknown_wh, 1),
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
    pool = None
    if before:
        pool = Pool(before[-1].get("stored_lb", 0.0), before[-1].get("unknown_wh", 0.0))
    estimate = (store.get_state("charging_estimates") or {}).get("estimate") or {}
    battery = Battery.from_dict(estimate.get("battery"))
    for day in days:
        totals = day_totals(store, day, pool, battery)
        if totals is not None:
            store.put_total(day, totals)
            pool = Pool(totals["stored_lb"], totals["unknown_wh"])
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
