"""What Cloud Scheduler triggers: a reading every 5 minutes, a plan every 30."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from planner.adaptive import build_adaptive_plan, estimates
from planner.plan import PACIFIC, build_plan

from solar_server import totals
from solar_server.config import Settings
from solar_server.sources import Sources
from solar_server.store import FORECASTS, MIX, PLANS, PLUG, SAMPLES, Store, day_key, window
from solar_server.totals import integrate_wh

log = logging.getLogger(__name__)


def _num(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


def collect(store: Store, sources: Sources, now: datetime) -> dict:
    """One sample: WattTime's latest marginal rate and percentile, plus the Jackery.

    Also stores CAISO's grid mix for the last hour and updates today's totals.

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
        record_sample(store, sample)
    store_mix(store, sources, now, since=t - 3600)
    try:
        totals.update(store, t)
    except Exception as e:
        log.warning("daily totals failed: %s", e)
    return sample


def record_sample(store: Store, sample: dict) -> None:
    """Keep the sample, and the latest one with today's solar total for /api/now."""
    today = _today(store, SAMPLES, "solar_w", store.get_state("sample"), sample)
    store.append(SAMPLES, sample)
    store.put_state("sample", {"sample": sample, "today": today})


def record_plug(store: Store, report: dict) -> None:
    """Keep the report, and the latest one with today's grid total for /api/now."""
    today = _today(store, PLUG, "w", store.get_state("plug"), report)
    store.append(PLUG, report)
    store.put_state("plug", {"report": report, "today": today})


def _today(store: Store, series: str, key: str, state: dict | None, item: dict) -> dict:
    """Today's energy from ``key`` watts so far, carried on from the last state.

    The first time, when there is no state yet, it counts what's already stored.
    """
    day = day_key(item["t"])
    last: tuple[int, float] | None = None
    if state is None:
        stored = store.day(series, day)
        points = sorted((i["t"], float(i[key])) for i in stored if i.get(key) is not None)
        wh, last = integrate_wh(points), (points[-1] if points else None)
    elif state["today"]["day"] == day:
        wh = state["today"]["wh"]
        if state["today"]["last"]:
            t, w = state["today"]["last"]
            last = (int(t), float(w))
    else:
        wh = 0.0
    if item.get(key) is not None and (last is None or item["t"] > last[0]):
        point = (int(item["t"]), float(item[key]))
        if last is not None:
            wh += integrate_wh([last, point])
        last = point
    return {"day": day, "wh": wh, "last": list(last) if last else None}


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
    """Refresh the emissions forecast and the battery-aware charging plan."""
    points = sources.forecast(24)
    if not any(now <= t < now + timedelta(hours=24) for t, _ in points) or not all(
        math.isfinite(v) for _, v in points
    ):
        raise ValueError("unusable emissions forecast; keeping the previous plan")
    p = charging_plan(store, points, settings, now)
    try:
        p["index_now"] = sources.signal_index()
    except Exception as e:
        log.warning("signal-index skipped: %s", e)
    p["forecast"] = [[int(t.timestamp()), round(v, 1)] for t, v in points]
    p["forecast_at"] = int(now.timestamp())
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


def charging_plan(
    store: Store, points: list[tuple[datetime, float]], settings: Settings, now: datetime
) -> dict:
    """Use recent battery telemetry; otherwise label the fixed-budget fallback."""
    t = int(now.timestamp())
    battery = (store.get_state("sample") or {}).get("sample")
    if battery is None or battery.get("battery_pct") is None:
        recent = window(store, SAMPLES, t - 900, t)
        battery = next((s for s in reversed(recent) if s.get("battery_pct") is not None), None)
    if (
        battery is None
        or not 0 <= t - battery["t"] <= 900
        or not 0 <= battery["battery_pct"] <= 100
    ):
        p = build_plan(
            points,
            now,
            budget_hours=settings.budget_hours,
            block_minutes=15,
            region=settings.region,
        )
        p["strategy"] = "fallback"
        return p
    estimate = charging_estimates(store, settings, t)
    return build_adaptive_plan(
        points,
        now,
        battery["battery_pct"],
        estimate,
        floor_pct=settings.floor_pct,
        region=settings.region,
    )


def charging_estimates(store: Store, settings: Settings, now: int) -> dict:
    """Read history at most twice an hour; replans normally use one state read."""
    inputs = [settings.solar_day_wh, settings.load_w, settings.charge_w]
    cached = store.get_state("charging_estimates") or {}
    if cached.get("inputs") == inputs and 0 <= now - cached.get("t", 0) < 1800:
        return cached["estimate"]
    samples = window(store, SAMPLES, now - 8 * 86400, now)
    estimate = estimates(samples, now, *inputs)
    store.put_state("charging_estimates", {"t": now, "inputs": inputs, "estimate": estimate})
    return estimate


def refresh_charging_plan(store: Store, settings: Settings, now: datetime) -> None:
    """Replan after each 5-minute reading using the cached emissions forecast."""
    old = store.get_state("plan") or {}
    forecast = old.get("forecast", [])
    if not forecast or int(now.timestamp()) - old.get("forecast_at", old["generated_at"]) > 7200:
        return
    points = [(datetime.fromtimestamp(t, now.tzinfo), v) for t, v in forecast]
    if not any(t >= now for t, _ in points):
        return
    p = charging_plan(store, points, settings, now)
    p.update(forecast=forecast, forecast_at=old.get("forecast_at", old["generated_at"]))
    p["index_now"] = old.get("index_now")
    store.put_state("plan", p)
    store.append(
        PLANS, {"t": p["generated_at"], "windows": [{"s": s, "e": e} for s, e in p["windows"]]}
    )


def plug_plan(store: Store) -> dict | None:
    """The plan as the plug reads it (the shape build_plan returns)."""
    p = store.get_state("plan")
    if p is None:
        return None
    return {k: v for k, v in p.items() if not k.startswith("forecast")}
