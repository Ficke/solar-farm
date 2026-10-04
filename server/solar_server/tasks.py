"""What Cloud Scheduler triggers: a reading every 5 minutes, a plan every 30."""

from __future__ import annotations

import logging
from datetime import datetime

from planner.plan import PACIFIC, build_plan

from solar_server.config import Settings
from solar_server.sources import Sources
from solar_server.store import FORECASTS, MIX, PLANS, SAMPLES, Store

log = logging.getLogger(__name__)


def _num(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


def collect(store: Store, sources: Sources, now: datetime) -> dict:
    """One sample: WattTime's latest marginal rate and percentile, plus the Jackery.

    Also stores CAISO's grid mix for the last hour.

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
    store_mix(store, sources, now, since=t - 3600)
    return sample


def store_mix(store: Store, sources: Sources, now: datetime, since: int) -> None:
    """CAISO's grid mix from ``since`` to now; rows already stored are skipped."""
    t = int(now.timestamp())
    today = now.astimezone(PACIFIC).date()
    days = sorted({datetime.fromtimestamp(since, PACIFIC).date(), today})
    for day in days:
        try:
            rows = sources.mix(day, now)
        except Exception as e:
            log.warning("caiso mix %s failed: %s", day, e)
            continue
        store.extend(MIX, [r for r in rows if since <= r["t"] <= t])


def plan(store: Store, sources: Sources, settings: Settings, now: datetime) -> dict:
    """Pick tomorrow's cleanest hours and keep the forecast for the dashboard."""
    points = sources.forecast(24)
    p = build_plan(points, now, budget_hours=settings.budget_hours, region=settings.region)
    try:
        p["index_now"] = sources.signal_index()
    except Exception as e:
        log.warning("signal-index skipped: %s", e)
    p["forecast"] = [[int(t.timestamp()), round(v, 1)] for t, v in points]
    # Fill any gaps in the last day's grid mix.
    store_mix(store, sources, now, since=int(now.timestamp()) - 86400)
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


def plug_plan(store: Store) -> dict | None:
    """The plan as the plug reads it (the shape build_plan returns)."""
    p = store.get_state("plan")
    if p is None:
        return None
    return {k: v for k, v in p.items() if not k.startswith("forecast")}
