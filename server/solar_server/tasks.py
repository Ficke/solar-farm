"""What Cloud Scheduler triggers: a reading every 5 minutes, a plan every 30."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from planner.plan import build_plan

from solar_server.config import Settings
from solar_server.sources import Sources
from solar_server.store import AOER, FORECASTS, HEALTH, PLANS, SAMPLES, Store

log = logging.getLogger(__name__)


def _num(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


# WattTime's other signals, published late: (series, signal, hours to refetch).
LATE_SIGNALS = ((AOER, "co2_aoer", 72), (HEALTH, "health_damage", 24))


def collect(store: Store, sources: Sources, now: datetime) -> dict:
    """One sample: WattTime's latest marginal rate and percentile, plus the Jackery.

    Each source is optional; a sample is stored with whatever arrived.
    """
    t = int(now.timestamp())
    sample: dict = {"t": t}
    try:
        point = sources.actual("co2_moer", now)
        if point:
            sample["moer"] = _num(point[1])
            sample["moer_t"] = int(point[0].timestamp())
    except Exception as e:
        log.warning("watttime co2_moer failed: %s", e)
    try:
        sample["index"] = _num(sources.signal_index())
    except Exception as e:
        log.warning("watttime signal-index failed: %s", e)
    try:
        r = sources.jackery(now)
        if r is not None:
            sample.update(
                battery_pct=_num(r.battery_pct),
                solar_w=_num(r.solar_w),
                ac_input_w=_num(r.ac_input_w),
                output_w=_num(r.output_w),
            )
    except Exception as e:  # unofficial API: never let it block the rest
        log.warning("jackery failed: %s", e)
    if len(sample) > 1:
        store.append(SAMPLES, sample)
    return sample


def plan(store: Store, sources: Sources, settings: Settings, now: datetime) -> dict:
    """Pick tomorrow's cleanest hours and keep the forecast for the dashboard."""
    points = sources.forecast(24)
    p = build_plan(points, now, budget_hours=settings.budget_hours, region=settings.region)
    try:
        p["index_now"] = sources.signal_index()
    except Exception as e:
        log.warning("signal-index skipped: %s", e)
    p["forecast"] = [[int(t.timestamp()), round(v, 1)] for t, v in points]
    # Health damage, for the dashboard only; the plan follows the marginal rate.
    try:
        health = sources.forecast(24, "health_damage")
        p["forecast_health"] = [[int(t.timestamp()), round(v, 2)] for t, v in health]
    except Exception as e:
        log.warning("watttime health_damage forecast failed: %s", e)
    backfill(store, sources, now)
    store.put_state("plan", p)
    # Keep every plan and forecast, so the dashboard can check the forecast
    # against what happened and later features can look back.
    store.append(
        PLANS,
        {"t": p["generated_at"], "windows": [{"s": s, "e": e} for s, e in p["windows"]]},
    )
    if points:
        store.append(
            FORECASTS,
            {
                "t": p["generated_at"],
                "start": int(points[0][0].timestamp()),
                "step": 300,
                "values": [round(v) for _, v in points],
            },
        )
    return p


def backfill(store: Store, sources: Sources, now: datetime) -> None:
    """Store the late-published signals for the last few days; repeats are skipped."""
    for series, signal, hours in LATE_SIGNALS:
        try:
            points = sources.history(signal, now - timedelta(hours=hours), now)
        except Exception as e:
            log.warning("watttime %s history failed: %s", signal, e)
            continue
        store.extend(series, [{"t": int(t.timestamp()), "v": round(v, 2)} for t, v in points])


def plug_plan(store: Store) -> dict | None:
    """The plan as the plug reads it (the shape build_plan returns)."""
    p = store.get_state("plan")
    if p is None:
        return None
    return {k: v for k, v in p.items() if not k.startswith("forecast")}
