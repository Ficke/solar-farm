"""Short grid top-ups from a battery trajectory, without Jackery mode controls.

This is a rolling, deadline-aware greedy planner, not a weather forecast or a
global optimum. It first keeps the battery above its floor, then replenishes
only as needed under a solar-aware ceiling, choosing the lowest MOER before each
deadline. Solar and load estimates come from observations.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import mean

from planner.plan import PACIFIC
from planner.telemetry import CAPACITY_WH


def estimates(
    samples: list[dict], now: int, solar_wh: float, load_w: float, charge_w: float
) -> dict:
    """Seven completed days of solar, one day of load, configured AC power.

    Solar days need 18 hours of coverage, including six between 9am and 5pm.
    Gaps over 15 minutes are excluded. Until then, use configured daily Wh
    distributed from 9am to 5pm. Load needs six hours of recent coverage.
    """
    samples = sorted({s["t"]: s for s in samples if s["t"] <= now}.values(), key=lambda s: s["t"])
    today = datetime.fromtimestamp(now, PACIFIC).date()
    first_day = today - timedelta(days=7)
    solar: dict[str, list[tuple[int, float]]] = defaultdict(list)
    load_energy = load_seconds = 0.0
    for s in samples:
        day = datetime.fromtimestamp(s["t"], PACIFIC).date()
        if (
            first_day <= day < today
            and s.get("solar_w") is not None
            and math.isfinite(s["solar_w"])
        ):
            day = day.isoformat()
            solar[day].append((s["t"], max(0.0, s["solar_w"])))
    profile: dict[int, list[float]] = defaultdict(list)
    daily = []
    for points in solar.values():
        buckets: dict[int, float] = defaultdict(float)
        coverage = daylight = wh = 0.0
        for (t0, w0), (t1, w1) in pairwise(points):
            if not 0 < t1 - t0 <= 900:
                continue
            energy = (w0 + w1) / 2 * (t1 - t0) / 3600
            local = datetime.fromtimestamp((t0 + t1) // 2, PACIFIC)
            buckets[local.hour * 4 + local.minute // 15] += energy
            coverage += t1 - t0
            if 9 <= local.hour < 17:
                daylight += t1 - t0
            wh += energy
        if coverage >= 18 * 3600 and daylight >= 6 * 3600:
            daily.append(wh)
            for quarter in range(96):
                profile[quarter].append(buckets[quarter] * 4)
    recent = [s for s in samples if now - 86400 <= s["t"] <= now]
    for a, b in pairwise(recent):
        if (
            a.get("output_w") is not None
            and b.get("output_w") is not None
            and math.isfinite(a["output_w"])
            and math.isfinite(b["output_w"])
            and 0 < b["t"] - a["t"] <= 900
        ):
            seconds = b["t"] - a["t"]
            load_energy += (max(0, a["output_w"]) + max(0, b["output_w"])) / 2 * seconds
            load_seconds += seconds
    if daily:
        ordered = sorted(daily)
        good_day = ordered[round(0.8 * (len(ordered) - 1))]
        shape = {q: mean(ws) for q, ws in profile.items()}
    else:
        good_day = solar_wh
        shape = {q: solar_wh / 8 if 36 <= q < 68 else 0.0 for q in range(96)}
    return {
        "solar_profile": shape,
        "solar_day_wh": good_day,
        "solar_days": len(daily),
        "load_w": load_energy / load_seconds if load_seconds >= 6 * 3600 else load_w,
        "charge_w": charge_w,
    }


def build_adaptive_plan(
    points: list[tuple[datetime, float]],
    now: datetime,
    battery_pct: float,
    estimate: dict,
    floor_pct: float = 20,
    efficiency: float = 0.9,
    region: str = "CAISO_NORTH",
) -> dict:
    """Allocate minute-rounded top-ups in 15-minute forecast blocks.

    The AC rate is wall input; efficiency and output load are accounted for.
    Grid additions are limited by the charge target and storage room through
    their deadline. An infeasible trajectory is reported, never hidden by
    scheduling during peak or outside the supplied forecast.
    """
    tnow = int(now.timestamp())
    floor = CAPACITY_WH * floor_pct / 100
    target = max(floor, CAPACITY_WH - estimate["solar_day_wh"])
    # Always leave at least 10% room; the target is ours, not an app reserve.
    target = min(target, CAPACITY_WH * 0.9)
    signals: dict[int, list[float]] = defaultdict(list)
    for t, value in points:
        ts = int(t.timestamp())
        if tnow <= ts < tnow + 86400 and math.isfinite(value):
            signals[ts // 900 * 900].append(value)
    end = min(tnow + 86400, max(signals, default=tnow - 900) + 900)
    # State documents use JSON, which turns integer dictionary keys into strings.
    profile = {int(q): w for q, w in estimate["solar_profile"].items()}
    slots: list[dict] = []
    for start in range(tnow // 900 * 900, end, 900):
        s, e = max(tnow, start), min(end, start + 900)
        local = datetime.fromtimestamp(s, PACIFIC)
        q = local.hour * 4 + local.minute // 15
        solar = profile.get(q, 0.0)
        hours = (e - s) / 3600
        slots.append(
            {
                "s": s,
                "e": e,
                "net": (solar * efficiency - estimate["load_w"] / efficiency) * hours,
                "max": estimate["charge_w"] * efficiency * hours,
                "moer": sum(signals[start]) / len(signals[start]) if start in signals else None,
                "allowed": start in signals and not 16 <= local.hour < 21,
            }
        )
    grid = [0.0] * len(slots)
    initial = CAPACITY_WH * battery_pct / 100
    # Sustain today's stored energy without filling an arbitrary grid target.
    # Solar may raise the battery above this; grid cannot fill above the ceiling.
    terminal = max(floor, min(initial, target))
    ranked = sorted(
        (i for i, slot in enumerate(slots) if slot["allowed"]),
        key=lambda i: (slots[i]["moer"], -slots[i]["s"]),
    )

    def trajectory() -> list[float]:
        level = initial
        out = []
        for i, slot in enumerate(slots):
            level = min(CAPACITY_WH, level + slot["net"] + grid[i])
            out.append(level)
        return out

    def fill(deadline: int, desired: float) -> None:
        levels = trajectory()
        if levels[deadline] >= desired:
            return
        for i in ranked:
            if i > deadline:
                continue
            need = desired - levels[deadline]
            if need <= 0.01:
                break
            room = min(CAPACITY_WH - max(levels[i : deadline + 1]), target - levels[i])
            amount = min(need, slots[i]["max"] - grid[i], room)
            if amount > 0:
                grid[i] += amount
                levels = trajectory()

    for i in range(len(slots)):
        fill(i, floor)
    if slots:
        fill(len(slots) - 1, terminal)
    windows: list[list[int]] = []
    for i, amount in enumerate(grid):
        if amount <= 0.01:
            continue
        slot = slots[i]
        seconds = min(
            slot["e"] - slot["s"], math.ceil(amount / (estimate["charge_w"] * efficiency) * 60) * 60
        )
        # Put partial windows at the block start so the floor deadline is met.
        s, e = slot["s"], slot["s"] + seconds
        grid[i] = seconds / 3600 * estimate["charge_w"] * efficiency
        if windows and windows[-1][1] == s:
            windows[-1][1] = e
        else:
            windows.append([s, e])
    levels = trajectory()
    shortfall = (
        max(0.0, floor - min(levels, default=initial), terminal - levels[-1]) if levels else 0
    )
    return {
        "generated_at": tnow,
        "region": region,
        "signal": "co2_moer",
        "strategy": "adaptive",
        "windows": windows,
        "target_pct": round(target / CAPACITY_WH * 100, 1),
        "floor_pct": floor_pct,
        "solar_day_wh": round(estimate["solar_day_wh"]),
        "solar_days": estimate["solar_days"],
        "load_w": round(estimate["load_w"], 1),
        "charge_w": round(estimate["charge_w"], 1),
        "grid_wh": round(sum(grid) / efficiency),
        "shortfall_wh": round(shortfall),
    }
