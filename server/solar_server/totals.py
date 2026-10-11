"""Aggregate energy and estimated CO2 per Pacific day.

Avoided CO2 is ``load_lb`` (the load drawn straight from the grid at the time
it ran) minus ``used_lb`` (emissions attributed to the energy it actually
used). Grid energy passed through to the load counts at its own rate. Grid
energy that charges the battery adds its emissions to a pool carried across
days; solar adds none. Load drawn from the battery removes its proportional
share, so stored energy counts when used, not when charged. Rates use
WattTime actuals in lb/MWh; missing rates count toward Wh only.

Avoided CO2 splits into two parts that sum to the total:

- ``solar_lb``: solar Wh reaching the load, directly or through the battery,
  at the grid rate when the load ran.
- ``shift_lb``: grid Wh reaching the load at the rate when the load ran, less
  the CO2 they carried. Negative when charging was dirtier than use.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from planner.battery import (
    DISCHARGE,
    MAX_GAP,
    Battery,
    Rate,
    integrate_wh,
    metered,
    series,
    spans,
)

from solar_server.store import PLUG, SAMPLES, Store, day_key, day_keys

log = logging.getLogger(__name__)

# Nothing was recorded before this; the first update fills in every day since.
FIRST_DAY = "2026-10-01"
RATE_GAP = 1800  # Carry each marginal rate for at most 30 minutes.
VERSION = 8  # Increment to recompute history from FIRST_DAY.
MIN_KNOWN_WH = 30  # About 1% of charge; below this the stored rate is noise.


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


@dataclass
class Pool:
    """Emissions carried by the energy in the battery.

    ``unknown_wh`` is charge of unknown origin, present when readings began.
    The load drawing it counts as if it ran from the grid at that moment, so
    it neither adds nor avoids CO2.
    """

    stored_lb: float = 0.0
    unknown_wh: float = 0.0
    solar_wh: float = 0.0  # Known-origin charge that came from solar.

    def lb_mwh(self, held_wh: float) -> float | None:
        """Return the CO2 in lb/MWh of the known-origin charge in ``held_wh``."""
        known = held_wh - self.unknown_wh
        return self.stored_lb / known * 1e6 if known >= MIN_KNOWN_WH else None


@dataclass
class LoadCo2:
    """Load Wh and its CO2 in lb: direct-grid baseline, attributed, and avoided by source."""

    wh: float = 0.0
    baseline_lb: float = 0.0
    used_lb: float = 0.0
    solar_lb: float = 0.0
    shift_lb: float = 0.0


def load_co2(
    samples: list[dict],
    plug: list[dict],
    rate: Rate,
    pool: Pool,
    battery: Battery,
    trace: list[dict] | None = None,
) -> LoadCo2:
    """Estimate the load from the battery's energy balance and attribute its CO2.

    While the plug supplies power, the Jackery passes it to the load first and
    charges with the rest; that grid energy counts at its own rate. Otherwise
    solar runs the load first, without CO2, and only the rest comes from the
    battery. Battery energy carries the CO2 of the grid energy put in,
    including charging losses, and the load takes its share when drawn.

    Battery draws take solar and grid charge in proportion. Updates ``pool``.
    Appends the stored charge's CO2 rate at the end of each span to ``trace``.
    """
    rates = [(s["t"], rate(s["t"])) for s in samples]
    out = LoadCo2()
    for span in spans(samples, plug, battery, rate):
        load, direct = span.load, span.direct
        points = [(t, r) for t, r in rates if span.t0 <= t <= span.t1]
        baseline_lb = sum(
            load * (span.done(u) - span.done(t)) * r / 1e6
            for (t, r), (u, _) in pairwise(points)
            if r is not None
        )
        direct_lb = span.grid_lb * direct / span.grid_wh if span.grid_wh > 0 else 0.0
        pool.stored_lb += span.grid_lb - direct_lb
        # Solar Wh reaching the inverter run the load before the battery does.
        need = (load - direct) / DISCHARGE
        drawn = max(0.0, need - span.solar_in)
        solar_load = min(need, span.solar_in) * DISCHARGE
        pool.solar_wh += max(0.0, span.solar_in - need)
        held = battery.wh(span.pct) + drawn
        unknown = min(1.0, pool.unknown_wh / held) if held > 0 else 1.0
        known = held - pool.unknown_wh
        known_drawn = drawn * (1 - unknown)
        part = min(1.0, known_drawn / known) if known > 0 else 0.0
        take = pool.stored_lb * part
        solar_drawn = known_drawn * min(1.0, pool.solar_wh / known) if known > 0 else 0.0
        pool.stored_lb -= take
        pool.solar_wh -= pool.solar_wh * part
        pool.unknown_wh = max(0.0, pool.unknown_wh - drawn * unknown)
        pool.solar_wh = min(pool.solar_wh, max(0.0, battery.wh(span.pct) - pool.unknown_wh))
        per_wh = baseline_lb / load if load > 0 else 0.0
        out.wh += load
        out.baseline_lb += baseline_lb
        out.used_lb += direct_lb + take + per_wh * drawn * DISCHARGE * unknown
        out.solar_lb += per_wh * (solar_load + solar_drawn * DISCHARGE)
        grid_load = direct + (known_drawn - solar_drawn) * DISCHARGE
        out.shift_lb += per_wh * grid_load - direct_lb - take
        stored = pool.lb_mwh(battery.wh(span.pct))
        if trace is not None and stored is not None:
            trace.append({"t": span.t1, "lb_mwh": round(stored)})
    return out


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
    by = metered(plug, rate)
    grid_wh, grid_lb = by(plug[-1]["t"]) if plug else (0.0, 0.0)
    stored_co2: list[dict] = []
    co2 = load_co2(samples, plug, rate, pool, battery, stored_co2)
    # Plug draw before the first or after the last change in charge goes into the battery.
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
        "load_wh": round(co2.wh, 1),
        "grid_wh": round(grid_wh, 1),
        "load_lb": round(co2.baseline_lb, 4),
        "grid_lb": round(grid_lb, 4),
        "used_lb": round(co2.used_lb, 4),
        "solar_lb": round(co2.solar_lb, 4),
        "shift_lb": round(co2.shift_lb, 4),
        "stored_lb": round(pool.stored_lb, 6),
        "unknown_wh": round(pool.unknown_wh, 1),
        "stored_solar_wh": round(pool.solar_wh, 1),
        "stored_co2": stored_co2,
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
        last_day = before[-1]
        pool = Pool(
            last_day.get("stored_lb", 0.0),
            last_day.get("unknown_wh", 0.0),
            last_day.get("stored_solar_wh", 0.0),
        )
    estimate = (store.get_state("charging_estimates") or {}).get("estimate") or {}
    battery = Battery.from_dict(estimate.get("battery"))
    for day in days:
        totals = day_totals(store, day, pool, battery)
        if totals is not None:
            store.put_total(day, totals)
            pool = Pool(totals["stored_lb"], totals["unknown_wh"], totals["stored_solar_wh"])
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
