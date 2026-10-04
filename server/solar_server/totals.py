"""Each day's energy and CO2, one small document per Pacific day.

Totals for any week, month or year are sums of these, so the dashboard never
has to read raw readings to aggregate.

CO2 avoided compares two ways of running the same load:

- without the battery: every Wh the Jackery put out would have come from the
  wall at that moment, at that moment's marginal rate (``load_lb``);
- what happened: the CO2 of the energy the load actually used (``used_lb``).
  Every Wh the plug draws adds its CO2, at the marginal rate when it was
  drawn, to the battery; solar adds energy but no CO2. The load takes CO2 out
  in proportion to the share of the battery's energy it uses.

``load_lb - used_lb`` is what the battery avoided. Energy only drops out of
the comparison through solar: grid energy stored one day and used the next
counts on the day it's used, so shifting doesn't look like saving. Charging
losses stay in the battery's CO2 and count against it. ``grid_lb`` is the CO2
of what the plug drew that day. The rate is WattTime's actual marginal CO2 for
CAISO_NORTH, in lb/MWh. Stretches with no rate from the last half hour count
toward Wh but not toward CO2.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Callable
from datetime import date, timedelta
from itertools import pairwise

from planner.telemetry import CAPACITY_WH

from solar_server.store import PLUG, SAMPLES, Store, day_key, day_keys

log = logging.getLogger(__name__)

# Nothing was recorded before this; the first update fills in every day since.
FIRST_DAY = "2026-10-01"
MAX_GAP = 3600  # don't integrate across outages longer than an hour
RATE_GAP = 1800  # use a marginal rate up to half an hour from when it applied
VERSION = 2  # bump to recompute every day from FIRST_DAY

type Rate = Callable[[float], float | None]


def rate_lookup(samples: list[dict]) -> Rate:
    """The marginal rate in force at each moment, from the samples' WattTime actuals.

    Each actual applies from its ``moer_t`` until the next one, for up to
    ``RATE_GAP`` seconds.
    """
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
    """Hours between readings, not counting outages longer than ``MAX_GAP``."""
    return sum(min(t1 - t0, MAX_GAP) for (t0, _), (t1, _) in pairwise(points)) / 3600


def integrate_wh(points: list[tuple[int, float]]) -> float:
    return energy(points, lambda _t: None)[0]


def energy(points: list[tuple[int, float]], rate: Rate) -> tuple[float, float]:
    """Wh, and lb of CO2 at the marginal rate when each Wh was used."""
    wh = lb = 0.0
    for (t0, w0), (t1, w1) in pairwise(points):
        seg = (w0 + w1) / 2 * min(t1 - t0, MAX_GAP) / 3600
        wh += seg
        r = rate((t0 + t1) / 2)
        if r is not None:
            lb += seg * r / 1e6
    return wh, lb


def cumulative(points: list[tuple[int, float]], rate: Rate) -> Callable[[float], float]:
    """lb of CO2 drawn from the start of ``points`` up to any moment."""
    times = [t for t, _ in points]
    sums = [0.0]
    for a, b in pairwise(points):
        sums.append(sums[-1] + energy([a, b], rate)[1])

    def at(t: float) -> float:
        i = bisect_right(times, t) - 1
        if i < 0:
            return 0.0
        if i >= len(points) - 1:
            return sums[-1]
        (t0, w0), (t1, w1) = points[i], points[i + 1]
        w = w0 + (w1 - w0) * (t - t0) / (t1 - t0)
        return sums[i] + energy([(t0, w0), (int(t), w)], rate)[1] if t > t0 else sums[i]

    return at


def used_co2(
    samples: list[dict], grid_lb_by: Callable[[float], float], stored_lb: float
) -> tuple[float, float]:
    """CO2 of the energy the load used, and the CO2 left in the battery after.

    Between readings, the plug's CO2 goes into the battery and the load takes
    out its share: the Wh it used over the Wh the battery held before it did.
    """
    used = 0.0
    rows = [s for s in samples if s.get("output_w") is not None]
    for a, b in pairwise(rows):
        stored_lb += grid_lb_by(b["t"]) - grid_lb_by(a["t"])
        out_wh = energy([(a["t"], a["output_w"]), (b["t"], b["output_w"])], lambda _t: None)[0]
        pct = b.get("battery_pct")
        held_wh = (pct if pct is not None else 50.0) / 100 * CAPACITY_WH + out_wh
        take = stored_lb * min(1.0, out_wh / held_wh) if held_wh > 0 else stored_lb
        used += take
        stored_lb -= take
    return used, stored_lb


def day_totals(store: Store, day: str, stored_lb: float | None = None) -> dict | None:
    """``stored_lb`` is the CO2 in the battery at the start of the day. Without
    it, whatever the battery first holds counts as grid energy at the first rate."""
    samples = sorted(store.day(SAMPLES, day), key=lambda s: s["t"])
    plug = sorted(store.day(PLUG, day), key=lambda r: r["t"])
    if not samples and not plug:
        return None
    rate = rate_lookup(samples)
    if stored_lb is None:
        first = next((s for s in samples if s.get("battery_pct") is not None), None)
        r = rate(first["t"]) if first else None
        stored_lb = first["battery_pct"] / 100 * CAPACITY_WH * r / 1e6 if first and r else 0.0

    def series(items: list[dict], key: str) -> list[tuple[int, float]]:
        return [(int(i["t"]), float(i[key])) for i in items if i.get(key) is not None]

    solar = series(samples, "solar_w")
    grid = series(plug, "w")
    load_wh, load_lb = energy(series(samples, "output_w"), rate)
    grid_wh, grid_lb = energy(grid, rate)
    by = cumulative(grid, rate)
    used_lb, stored_lb = used_co2(samples, by, stored_lb)
    # Plug draw before the first or after the last reading goes into the battery too.
    if samples:
        stored_lb += by(samples[0]["t"]) + grid_lb - by(samples[-1]["t"])
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
    """Stored day totals from ``since`` to ``until``; days without data are left out."""
    return store.totals(day_keys(since, until))
