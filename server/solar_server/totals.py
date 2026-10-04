"""Each day's energy and CO2, one small document per Pacific day.

Totals for any week, month or year are sums of these, so the dashboard never
has to read raw readings to aggregate.

CO2 avoided compares two ways of running the same load:

- without the battery: every Wh the Jackery put out would have come from the
  wall at that moment, at that moment's marginal rate (``load_lb``);
- what happened: every Wh the plug let through from the wall, at the marginal
  rate when it was drawn (``grid_lb``).

``load_lb - grid_lb`` is what the battery avoided. Solar and charging at
cleaner times count for it; charging losses count against it. The rate is
WattTime's actual marginal CO2 for CAISO_NORTH, in lb/MWh. Stretches with no
rate from the last half hour count toward Wh but not toward either CO2 total.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Callable
from datetime import date, timedelta
from itertools import pairwise

from solar_server.store import PLUG, SAMPLES, Store, day_key, day_keys

log = logging.getLogger(__name__)

# Nothing was recorded before this; the first update fills in every day since.
FIRST_DAY = "2026-10-01"
MAX_GAP = 3600  # don't integrate across outages longer than an hour
RATE_GAP = 1800  # use a marginal rate up to half an hour from when it applied

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


def day_totals(store: Store, day: str) -> dict | None:
    samples = sorted(store.day(SAMPLES, day), key=lambda s: s["t"])
    plug = sorted(store.day(PLUG, day), key=lambda r: r["t"])
    if not samples and not plug:
        return None
    rate = rate_lookup(samples)

    def series(items: list[dict], key: str) -> list[tuple[int, float]]:
        return [(int(i["t"]), float(i[key])) for i in items if i.get(key) is not None]

    solar = series(samples, "solar_w")
    load_wh, load_lb = energy(series(samples, "output_w"), rate)
    grid_wh, grid_lb = energy(series(plug, "w"), rate)
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
        "battery_peak_pct": max(peaks) if peaks else None,
    }


def update(store: Store, now: int) -> list[str]:
    """Recompute every day from the last one updated through today.

    Normally that's just today, plus yesterday right after midnight. The first
    run, and the first after the collector has been down, fill in the gap.
    """
    last = (store.get_state("totals") or {}).get("day", FIRST_DAY)
    today = day_key(now)
    days = _days_from(last, today)
    for day in days:
        totals = day_totals(store, day)
        if totals is not None:
            store.put_total(day, totals)
    store.put_state("totals", {"day": today})
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
