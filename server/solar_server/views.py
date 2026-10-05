"""Build dashboard responses from stored data."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from planner.battery import Battery
from planner.plan import PACIFIC

from planner import telemetry
from solar_server import totals
from solar_server.store import FORECASTS, MIX, PLUG, PRICES, SAMPLES, Store, day_key, window


def now_view(store: Store, now: int) -> dict:
    """Read live data and today's totals from four state documents."""
    sample = store.get_state("sample") or {}
    estimate = (store.get_state("charging_estimates") or {}).get("estimate") or {}
    solar_scale = Battery.from_dict(estimate.get("battery")).solar_scale
    plug = store.get_state("plug") or {}
    today = day_key(now)

    def latest(state: dict, key: str, max_age: int) -> dict | None:
        item = state.get(key)
        return item if item and item["t"] >= now - max_age else None

    def wh(state: dict, scale: float = 1.0) -> int:
        t = state.get("today")
        return round(t["wh"] * scale) if t and t["day"] == today else 0

    plan = store.get_state("plan") or {}
    return {
        "now": now,
        "sample": latest(sample, "sample", 2 * 3600),
        "plug": latest(plug, "report", 3600),
        "today": {"solar_wh": wh(sample, solar_scale), "grid_wh": wh(plug)},
        "plan": {
            k: v
            for k, v in plan.items()
            if k
            in (
                "generated_at",
                "windows",
                "index_now",
                "strategy",
                "target_pct",
                "deadline",
                "floor_pct",
                "solar_day_wh",
                "solar_days",
                "load_w",
                "charge_w",
                "grid_wh",
                "bypass_wh",
                "blocks",
                "shortfall_wh",
                "forecast_at",
                "forecast_until",
                "missing",
                "zeros_doubted_since",
            )
        }
        if plan
        else None,
    }


def timeline_view(store: Store, now: int, past_hours: int = 24) -> dict:
    since = now - past_hours * 3600
    plan = store.get_state("plan") or {}
    return {
        "now": now,
        "since": since,
        "samples": window(store, SAMPLES, since, now),
        "plug": [
            {k: r.get(k) for k in ("t", "on", "reason", "w")}
            for r in window(store, PLUG, since, now)
        ],
        "forecast": [p for p in plan.get("forecast", []) if p[0] >= now - 300],
        # CAISO sometimes revises a row; the latest stored copy wins.
        "mix": list({i["t"]: i for i in window(store, MIX, since, now)}.values()),
        "prices": list({i["t"]: i for i in window(store, PRICES, since, now)}.values()),
        "windows": plan.get("windows", []),
    }


def daily_view(store: Store, now: int, days: int = 14) -> dict:
    stored = totals.read(store, now - days * 86400, now)
    rows = [
        {
            "day": d["day"],
            "solar_wh": round(d["solar_wh"]),
            "grid_wh": round(d["grid_wh"]),
            "load_wh": round(d.get("load_wh", 0)),
            "battery_peak_pct": d.get("battery_peak_pct"),
        }
        for d in stored
    ]
    # Legacy totals lack solar_h; infer coverage from their five-minute samples.
    today = day_key(now)
    full = {
        d["day"]: d["solar_wh"]
        for d in stored
        if d.get("solar_h", d["solar_n"] / 12) >= 3 and d["day"] != today
    }
    return {"days": rows, "reserve": telemetry.recommend_reserve(full)}


def co2_view(store: Store, now: int, by: str = "day", count: int = 14) -> dict:
    """Group avoided CO2 by Pacific day, Monday-based week or month, oldest first."""
    today = datetime.fromtimestamp(now, PACIFIC).date()
    if by == "day":
        first = today - timedelta(days=count - 1)
    elif by == "week":
        first = today - timedelta(days=today.weekday() + 7 * (count - 1))
    else:
        months = today.year * 12 + today.month - 1 - (count - 1)
        first = date(months // 12, months % 12 + 1, 1)
    since = int(datetime.combine(first, time(12), PACIFIC).timestamp())
    periods: dict[str, dict] = {}
    for d in totals.read(store, since, now):
        day = date.fromisoformat(d["day"])
        if by == "week":
            key = (day - timedelta(days=day.weekday())).isoformat()
        elif by == "month":
            key = day.isoformat()[:7]
        else:
            key = d["day"]
        p = periods.setdefault(key, {"start": key, **dict.fromkeys(CO2_SUMS, 0.0)})
        for k in CO2_SUMS:
            p[k] += d.get(k, 0.0)
    return {
        "by": by,
        "periods": [_co2_row(p) for p in sorted(periods.values(), key=lambda p: p["start"])],
    }


CO2_SUMS = ("load_wh", "grid_wh", "solar_wh", "load_lb", "grid_lb", "used_lb")


def _co2_row(p: dict) -> dict:
    return {
        "start": p["start"],
        **{k: round(p[k]) for k in ("load_wh", "grid_wh", "solar_wh")},
        "load_lb": round(p["load_lb"], 3),
        "grid_lb": round(p["grid_lb"], 3),
        "used_lb": round(p["used_lb"], 3),
        "avoided_lb": round(p["load_lb"] - p["used_lb"], 3),
    }


def accuracy_view(store: Store, now: int, lead_hours: int = 6, past_hours: int = 24) -> dict:
    """Compare actuals with the latest forecast at least ``lead_hours`` earlier.

    Return mean absolute error across matched readings.
    """
    since = now - past_hours * 3600
    lead = lead_hours * 3600
    snapshots = window(store, FORECASTS, since - lead - 86400, now)
    points: list[list[float | int | None]] = []
    errors: list[float] = []
    for s in window(store, SAMPLES, since, now):
        if s.get("moer") is None:
            continue
        t = s.get("moer_t", s["t"])
        predicted = None
        for f in reversed(snapshots):
            if f["t"] > t - lead:
                continue
            i = (t - f["start"]) // f["step"]
            if 0 <= i < len(f["values"]):
                predicted = f["values"][i]
            break
        points.append([t, s["moer"], predicted])
        if predicted is not None:
            errors.append(abs(s["moer"] - predicted))
    return {
        "lead_hours": lead_hours,
        "points": points,
        "error": round(sum(errors) / len(errors)) if errors else None,
        "compared": len(errors),
    }
