"""How much the grid has to put into the battery before the next 4 pm peak.

The battery should be back at the Jackery's reserve when the peak starts.
Solar counts first: the grid covers only what the battery, plus the solar
still expected before then, minus the load, leaves short. Solar and load are
expected to follow the last week's readings at the same time of day, and the
charge rate is what the grid has actually managed. Every plan run starts
again from the live battery level, so a sunny day drops grid time and a
cloudy one adds it.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from statistics import median

from planner.plan import PACIFIC
from planner.telemetry import CAPACITY_WH

STEP = 300  # samples arrive every 5 minutes
BUCKET = 1800  # solar and load are averaged by half-hour of the day


def next_deadline(now: datetime, peak_start_hour: int = 16) -> datetime:
    """The next start of the peak, local time."""
    local = now.astimezone(PACIFIC)
    day = local.date()
    deadline = datetime.combine(day, time(peak_start_hour), PACIFIC)
    if local >= deadline:
        deadline = datetime.combine(day + timedelta(days=1), time(peak_start_hour), PACIFIC)
    return deadline


def grid_need(
    samples: list[dict],
    now: datetime,
    reserve_pct: float = 80.0,
    capacity_wh: float = CAPACITY_WH,
    block_minutes: int = 30,
    default_rate_w: float = 1000.0,
    history_days: int = 7,
    max_age: int = 1800,
    peak_start_hour: int = 16,
) -> dict | None:
    """Grid energy and half-hours needed by the next peak, or None without a battery reading.

    ``samples`` are the stored 5-minute readings (``t``, ``battery_pct``,
    ``solar_w``, ``ac_input_w``, ``output_w``) for at least ``history_days``.
    """
    t_now = int(now.timestamp())
    since = t_now - history_days * 86400
    recent = [s for s in samples if since <= s["t"] <= t_now]
    latest = next(
        (s for s in sorted(recent, key=lambda s: -s["t"]) if s.get("battery_pct") is not None),
        None,
    )
    if latest is None or latest["t"] < t_now - max_age:
        return None

    deadline = next_deadline(now, peak_start_hour)
    t_end = int(deadline.timestamp())
    solar = _profile(recent, "solar_w")
    load = _profile(recent, "output_w")
    load_default = _mean([s["output_w"] for s in recent if s.get("output_w") is not None])
    solar_wh = _expected(solar, t_now, t_end, 0.0)
    load_wh = _expected(load, t_now, t_end, load_default)

    # What the grid adds to the battery: AC in less what passes straight
    # through to the load. Below 200 W it's passthrough, not charging.
    charging = [
        s["ac_input_w"] - (s.get("output_w") or 0.0)
        for s in recent
        if s.get("ac_input_w") is not None
    ]
    charging = [w for w in charging if w >= 200]
    rate_w = median(charging) if len(charging) >= 3 else default_rate_w

    battery_wh = latest["battery_pct"] / 100 * capacity_wh
    target_wh = reserve_pct / 100 * capacity_wh
    grid_wh = max(0.0, target_wh - battery_wh - solar_wh + load_wh)
    per_block = rate_w * block_minutes / 60
    # One spare block covers charger losses and a forecast that falls short.
    blocks = math.ceil(grid_wh / per_block) + 1 if grid_wh > 0 else 0
    return {
        "deadline": t_end,
        "battery_pct": latest["battery_pct"],
        "reserve_pct": reserve_pct,
        "solar_wh": round(solar_wh),
        "load_wh": round(load_wh),
        "grid_wh": round(grid_wh),
        "rate_w": round(rate_w),
        "blocks": blocks,
    }


def _bucket(t: int) -> int:
    local = datetime.fromtimestamp(t, PACIFIC)
    return (local.hour * 3600 + local.minute * 60) // BUCKET


def _profile(samples: list[dict], key: str) -> dict[int, float]:
    """Mean watts for each half-hour of the day."""
    by: dict[int, list[float]] = {}
    for s in samples:
        if s.get(key) is not None:
            by.setdefault(_bucket(s["t"]), []).append(float(s[key]))
    return {b: _mean(v) for b, v in by.items()}


def _expected(profile: dict[int, float], start: int, end: int, default: float) -> float:
    """Watt-hours from ``start`` to ``end`` if each half-hour looks like its average."""
    wh = 0.0
    for t in range(start, end, STEP):
        wh += profile.get(_bucket(t), default) * min(STEP, end - t) / 3600
    return wh


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
