"""Collect telemetry and rebuild charging plans for Cloud Scheduler."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from planner.adaptive import MIN_CHARGE_W, build_adaptive_plan, estimates
from planner.battery import Battery
from planner.plan import PACIFIC, build_plan

from solar_server import totals
from solar_server.config import Settings
from solar_server.sources import Sources
from solar_server.store import (
    FORECASTS,
    MIX,
    PLANS,
    PLUG,
    PRICES,
    SAMPLES,
    Store,
    day_key,
    window,
)
from solar_server.totals import integrate_wh

log = logging.getLogger(__name__)


def _num(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


def collect(store: Store, sources: Sources, now: datetime) -> dict:
    """Store available Jackery data and newly published WattTime readings.

    Every five minutes, backfill an hour of CAISO mix and prices and update totals.
    Source failures do not discard other readings.
    """
    t = int(now.timestamp())
    sample: dict = {"t": t}
    five = now.minute % 5 == 0
    try:
        point = sources.actual("co2_moer", now)
        last = ((store.get_state("sample") or {}).get("sample") or {}).get("moer_t")
        if point and int(point[0].timestamp()) != last:
            sample["moer"] = _num(point[1])
            sample["moer_t"] = int(point[0].timestamp())
    except Exception as e:
        log.warning("watttime co2_moer failed: %s", e)
    if "moer" in sample:
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
    except Exception as e:
        log.warning("jackery failed: %s", e)
    if len(sample) > 1:
        record_sample(store, sample)
    if five:
        store_mix(store, sources, now, since=t - 3600)
        store_prices(store, sources, now, since=t - 3600)
        try:
            totals.update(store, t)
        except Exception as e:
            log.warning("daily totals failed: %s", e)
    return sample


WATTTIME_KEYS = ("moer", "moer_t", "index")
WATTTIME_KEEP = 1800  # Carry live WattTime readings for at most 30 minutes.


def record_sample(store: Store, sample: dict) -> None:
    """Archive the sample and update live solar totals, carrying recent WattTime data."""
    state = store.get_state("sample")
    today = _today(store, SAMPLES, "solar_w", state, sample)
    store.append(SAMPLES, sample)
    latest = dict(sample)
    last = (state or {}).get("sample") or {}
    if "moer" not in sample and 0 <= sample["t"] - last.get("moer_t", 0) <= WATTTIME_KEEP:
        latest.update({k: last[k] for k in WATTTIME_KEYS if k in last})
    store.put_state("sample", {"sample": latest, "today": today})


def record_plug(store: Store, report: dict) -> None:
    """Archive the report and update live grid totals."""
    today = _today(store, PLUG, "w", store.get_state("plug"), report)
    store.append(PLUG, report)
    store.put_state("plug", {"report": report, "today": today})


def _today(store: Store, series: str, key: str, state: dict | None, item: dict) -> dict:
    """Accumulate today's Wh, recovering stored history if state is missing."""
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
    """Store CAISO rows from ``since`` to now, skipping exact duplicates."""
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


def store_prices(store: Store, sources: Sources, now: datetime, since: int) -> None:
    """Store hub prices from ``since`` to now, skipping exact duplicates."""
    t = int(now.timestamp())
    try:
        rows = sources.prices(datetime.fromtimestamp(since, UTC), now)
    except Exception as e:
        log.warning("caiso prices failed: %s", e)
        return
    store.extend(PRICES, [r for r in rows if since <= r["t"] <= t])


def archive_due(now: datetime) -> bool:
    """Archive forecasts at half-hour marks."""
    return now.minute % 30 == 0


def plan(
    store: Store, sources: Sources, settings: Settings, now: datetime, archive: bool = True
) -> dict:
    """Refresh the emissions forecast and the battery-aware charging plan.

    The latest forecast lives in ``state/plan``. With ``archive``, the forecast
    is also kept in ``forecasts`` and the last day's grid mix and prices are filled in.
    """
    points = clean_forecast(sources.forecast(24))
    if not any(now <= t < now + timedelta(hours=24) for t, _ in points):
        raise ValueError("unusable emissions forecast; keeping the previous plan")
    p = charging_plan(store, live_check(store, points, now), settings, now)
    note_inputs(p, points, int(now.timestamp()))
    p["zeros_doubted_since"] = (store.get_state("zero_check") or {}).get("since")
    # Reuse the percentile collected with the latest WattTime reading.
    p["index_now"] = ((store.get_state("sample") or {}).get("sample") or {}).get("index")
    if p["index_now"] is None:
        try:
            p["index_now"] = sources.signal_index()
        except Exception as e:
            log.warning("signal-index skipped: %s", e)
    p["forecast"] = [[int(t.timestamp()), round(v, 1)] for t, v in points]
    if archive:
        # Fill any gaps in the last day's grid mix and prices.
        store_mix(store, sources, now, since=int(now.timestamp()) - 86400)
        store_prices(store, sources, now, since=int(now.timestamp()) - 86400)
    old = store.get_state("plan") or {}
    store.put_state("plan", p)
    keep_plan(store, old, p)
    # Preserve forecasts for comparison with later actual emissions.
    if archive and points:
        # Values sit on a 5-minute grid from the first point; a gap stays null.
        start = int(points[0][0].timestamp())
        values: list[int | None] = [None] * ((int(points[-1][0].timestamp()) - start) // 300 + 1)
        for t, v in points:
            values[(int(t.timestamp()) - start) // 300] = round(v)
        store.append(
            FORECASTS, {"t": p["generated_at"], "start": start, "step": 300, "values": values}
        )
    return p


def clean_forecast(points: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """Sort and deduplicate rates, excluding non-finite or negative values.

    Keep real zeros because they can represent renewable curtailment.
    """
    by_time = {t: v for t, v in points if math.isfinite(v) and v >= 0}
    return sorted(by_time.items())


LIVE_HIGH = 300  # Doubt zero forecasts at or above this live rate in lb/MWh.
LIVE_CLEAN = 100  # Clear doubt below this live rate in lb/MWh.
LIVE_MAX_AGE = 900


def live_check(
    store: Store, points: list[tuple[datetime, float]], now: datetime
) -> list[tuple[datetime, float]]:
    """Replace current-block forecasts with a fresh WattTime actual.

    When a high actual contradicts a zero forecast, replace today's other zeros
    with that recorded rate. Persist doubt until a clean actual or a new Pacific day.
    """
    t = int(now.timestamp())
    today = now.astimezone(PACIFIC).date().isoformat()
    check = store.get_state("zero_check") or {}
    doubt: dict[str, Any] = (
        dict(check) if check.get("day") == today else {"day": today, "since": None}
    )
    live = (store.get_state("sample") or {}).get("sample") or {}
    moer, moer_t = live.get("moer"), live.get("moer_t")
    rate = None
    if moer is not None and moer_t is not None and 0 <= t - moer_t <= LIVE_MAX_AGE:
        rate = float(moer)
        forecast_now = next((v for p_t, v in points if p_t.timestamp() >= moer_t), None)
        if rate >= LIVE_HIGH and forecast_now == 0 and doubt["since"] is None:
            doubt.update(since=moer_t, rate=rate)
        elif rate < LIVE_CLEAN:
            doubt = {"day": today, "since": None}
    if doubt != check:
        store.put_state("zero_check", doubt)
    block = t // 900 * 900
    doubted = doubt["since"] is not None
    out = []
    for p_t, v in points:
        if rate is not None and block <= p_t.timestamp() < block + 900:
            v = rate
        elif doubted and v == 0 and p_t.astimezone(PACIFIC).date().isoformat() == today:
            v = float(doubt["rate"])
        out.append((p_t, v))
    return out


FORECAST_STALE = 600  # Flag forecasts older than ten minutes.


def note_inputs(p: dict, points: list[tuple[datetime, float]], forecast_at: int) -> None:
    """Record what the plan was built from and which inputs were missing or stale."""
    p["forecast_at"] = forecast_at
    p["forecast_until"] = int(points[-1][0].timestamp()) + 300
    missing = []
    if p.get("strategy") == "fallback":
        missing.append("battery")
    if p["generated_at"] - forecast_at > FORECAST_STALE:
        missing.append("forecast")
    if p["forecast_until"] < p.get("deadline", 0):
        missing.append("forecast_horizon")
    p["missing"] = missing


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
    p = build_adaptive_plan(
        points,
        now,
        battery["battery_pct"],
        estimate,
        floor_pct=settings.floor_pct,
        region=settings.region,
        hold=(store.get_state("plan") or {}).get("windows"),
    )
    # The plug checks this reading's age before allowing peak power at low battery.
    p["battery_at"] = battery["t"]
    return p


ESTIMATES_MAX_AGE = 1800
ESTIMATES_MAX_AGE_CHARGING = 300  # Detect charging-speed changes sooner.


def charging_estimates(store: Store, settings: Settings, now: int) -> dict:
    """Cache history estimates for 30 minutes, or five while AC charging is detected."""
    inputs = [settings.solar_day_wh, settings.load_w, settings.charge_w]
    cached = store.get_state("charging_estimates") or {}
    latest = (store.get_state("sample") or {}).get("sample") or {}
    into_battery = (latest.get("ac_input_w") or 0) - max(0.0, latest.get("output_w") or 0)
    charging = into_battery >= MIN_CHARGE_W
    max_age = ESTIMATES_MAX_AGE_CHARGING if charging else ESTIMATES_MAX_AGE
    if cached.get("inputs") == inputs and 0 <= now - cached.get("t", 0) < max_age:
        return cached["estimate"]
    samples = window(store, SAMPLES, now - 8 * 86400, now)
    plug = window(store, PLUG, now - 8 * 86400, now)
    previous = Battery.from_dict((cached.get("estimate") or {}).get("battery"))
    estimate = estimates(samples, now, *inputs, plug=plug, battery=previous)
    store.put_state("charging_estimates", {"t": now, "inputs": inputs, "estimate": estimate})
    return estimate


def refresh_charging_plan(store: Store, settings: Settings, now: datetime) -> None:
    """Replan after each reading using the cached emissions forecast."""
    old = store.get_state("plan") or {}
    forecast = old.get("forecast", [])
    if not forecast or int(now.timestamp()) - old.get("forecast_at", old["generated_at"]) > 7200:
        return
    points = clean_forecast([(datetime.fromtimestamp(t, now.tzinfo), v) for t, v in forecast])
    if not any(t >= now for t, _ in points):
        return
    p = charging_plan(store, live_check(store, points, now), settings, now)
    note_inputs(p, points, old.get("forecast_at", old["generated_at"]))
    p["zeros_doubted_since"] = (store.get_state("zero_check") or {}).get("since")
    p["forecast"] = forecast
    p["index_now"] = old.get("index_now")
    store.put_state("plan", p)
    keep_plan(store, old, p)


def keep_plan(store: Store, old: dict, new: dict) -> None:
    """Keep five-minute snapshots and window changes to limit document growth."""
    changed = [list(w) for w in new["windows"]] != [list(w) for w in old.get("windows", [])]
    if changed or new["generated_at"] % 300 < 60:
        store.append(PLANS, plan_record(new))


PLAN_HISTORY_KEYS = (
    "strategy",
    "battery_pct",
    "deadline",
    "grid_wh",
    "bypass_wh",
    "shortfall_wh",
    "solar_day_wh",
    "solar_days",
    "load_w",
    "charge_w",
    "forecast_at",
    "forecast_until",
    "missing",
    "zeros_doubted_since",
)


def plan_record(p: dict) -> dict:
    """Return windows and decision inputs for plan history."""
    return {
        "t": p["generated_at"],
        "windows": [{"s": s, "e": e} for s, e in p["windows"]],
        **{k: p[k] for k in PLAN_HISTORY_KEYS if k in p},
    }


def plug_plan(store: Store) -> dict | None:
    """Return the current plan without forecast data."""
    p = store.get_state("plan")
    if p is None:
        return None
    # The Shelly parses this on a small heap; the per-block detail is for the dashboard.
    return {k: v for k, v in p.items() if not k.startswith("forecast") and k != "blocks"}
