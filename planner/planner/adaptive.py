"""Grid windows that leave the battery full by 4 pm, bought when the grid is cleanest.

A rolling greedy plan rebuilt from the live battery level, not a weather
forecast or a global optimum. Solar and load estimates come from observations.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, time, timedelta
from itertools import pairwise
from statistics import mean, median

from planner.plan import PACIFIC
from planner.telemetry import CAPACITY_WH

TIE_MOER = 50  # lb/MWh; forecasts this close count as equally clean
MIN_SOLAR_WH = 150  # later solar below this is not worth keeping room for
MIN_CHARGE_W = 200  # less than this into the battery is passthrough, not charging
MIN_CHARGE_READINGS = 3
RECENT_CHARGE_READINGS = 30  # about the last half hour of charging
TOLERANCE_WH = 30  # about 1%; smaller floor and full shortfalls are ignored


def estimates(
    samples: list[dict], now: int, solar_wh: float, load_w: float, charge_w: float
) -> dict:
    """Seven completed days of solar, one day of load, a week of AC charging.

    Solar days need six hours of coverage between 9am and 5pm; gaps over 15
    minutes are excluded. Until then, use configured daily Wh
    distributed from 9am to 5pm. Load needs six hours of recent coverage.
    The charge rate is the median grid power going into the battery (AC in
    less load) over the last RECENT_CHARGE_READINGS readings of at least
    MIN_CHARGE_W in the past week, so a charge running slow today counts
    within minutes. Below MIN_CHARGE_READINGS, the configured rate.
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
        daylight = wh = 0.0
        for (t0, w0), (t1, w1) in pairwise(points):
            if not 0 < t1 - t0 <= 900:
                continue
            energy = (w0 + w1) / 2 * (t1 - t0) / 3600
            local = datetime.fromtimestamp((t0 + t1) // 2, PACIFIC)
            buckets[local.hour * 4 + local.minute // 15] += energy
            if 9 <= local.hour < 17:
                daylight += t1 - t0
            wh += energy
        if daylight >= 6 * 3600:
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
    charging = [
        w
        for s in samples
        if now - 7 * 86400 <= s["t"]
        and s.get("ac_input_w") is not None
        and math.isfinite(s["ac_input_w"])
        and math.isfinite(s.get("output_w") or 0.0)
        and (w := s["ac_input_w"] - max(0.0, s.get("output_w") or 0.0)) >= MIN_CHARGE_W
    ][-RECENT_CHARGE_READINGS:]
    if daily:
        good_day = mean(daily)
        shape = {q: mean(ws) for q, ws in profile.items()}
    else:
        good_day = solar_wh
        shape = {q: solar_wh / 8 if 36 <= q < 68 else 0.0 for q in range(96)}
    return {
        "solar_profile": shape,
        "solar_day_wh": good_day,
        "solar_days": len(daily),
        "load_w": load_energy / load_seconds if load_seconds >= 6 * 3600 else load_w,
        "charge_w": median(charging) if len(charging) >= MIN_CHARGE_READINGS else charge_w,
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
    """Plan grid time so the battery is full by the next 4 pm.

    Grid energy is whatever expected solar and load leave short of full. It is
    bought in the cleanest 15-minute forecast blocks before 4 pm; blocks within
    TIE_MOER of each other count as equal and the later one wins, so solar gets
    in first. Grid fills to full except for room kept for later solar, which
    counts half the usual output and only when that is at least MIN_SOLAR_WH:
    a little solar is not worth missing a clean window for. The battery never
    plans below its floor. An infeasible plan is reported, never hidden by
    scheduling during peak or outside the supplied forecast.
    """
    tnow = int(now.timestamp())
    floor = CAPACITY_WH * floor_pct / 100
    target = CAPACITY_WH
    deadline = next_deadline(now)
    signals: dict[int, list[float]] = defaultdict(list)
    for t, value in points:
        ts = int(t.timestamp())
        # Points from the start of the current block keep it plannable until it ends.
        if tnow // 900 * 900 <= ts < deadline and math.isfinite(value):
            signals[ts // 900 * 900].append(value)
    end = min(deadline, max(signals, default=tnow - 900) + 900)
    # State documents use JSON, which turns integer dictionary keys into strings.
    profile = {int(q): w for q, w in estimate["solar_profile"].items()}
    slots: list[dict] = []
    for start in range(tnow // 900 * 900, end, 900):
        s, e = max(tnow, start), min(end, start + 900)
        local = datetime.fromtimestamp(s, PACIFIC)
        hours = (e - s) / 3600
        solar = profile.get(local.hour * 4 + local.minute // 15, 0.0) * efficiency * hours
        moer = sum(signals[start]) / len(signals[start]) if start in signals else None
        slots.append(
            {
                "s": s,
                "e": e,
                "solar": solar,
                "net": solar - estimate["load_w"] / efficiency * hours,
                "max": estimate["charge_w"] * efficiency * hours,
                "moer": moer,
                "allowed": moer is not None and not 16 <= local.hour < 21,
            }
        )
    # Room kept for solar still to come after each block.
    later = [0.0] * len(slots)
    for i in range(len(slots) - 2, -1, -1):
        later[i] = later[i + 1] + slots[i + 1]["solar"]
    keep = [h / 2 if h / 2 >= MIN_SOLAR_WH else 0.0 for h in later]
    grid = [0.0] * len(slots)
    initial = CAPACITY_WH * battery_pct / 100
    ranked = sorted(
        (i for i, slot in enumerate(slots) if slot["allowed"]),
        key=lambda i: (round(slots[i]["moer"] / TIE_MOER), -slots[i]["s"]),
    )

    def trajectory() -> list[float]:
        level = initial
        out = []
        for i, slot in enumerate(slots):
            level = min(CAPACITY_WH, level + slot["net"] + grid[i])
            out.append(level)
        return out

    def fill(by: int, desired: float) -> None:
        """Add only what the level at block ``by`` needs to reach ``desired``."""
        for i in ranked:
            levels = trajectory()
            need = desired - levels[by]
            if need <= TOLERANCE_WH:
                break
            if i <= by:
                before = levels[i - 1] if i else initial
                room = CAPACITY_WH - before - slots[i]["net"] - grid[i]
                grid[i] += max(0.0, min(slots[i]["max"] - grid[i], need, room))

    for i in range(len(slots)):
        fill(i, floor)
    # Fill to full in the cleanest blocks, leaving room for material later
    # solar, and stop at the first block that reaches that ceiling.
    for i in ranked:
        levels = trajectory()
        before = levels[i - 1] if i else initial
        room = target - keep[i] - before - slots[i]["net"] - sum(grid[i:])
        grid[i] += max(0.0, min(slots[i]["max"] - grid[i], room))
        if grid[i] < slots[i]["max"] - 0.01:
            break
    # Cover what load still drains, or what the clean blocks couldn't fit.
    if slots:
        fill(len(slots) - 1, target)
    windows: list[list[int]] = []
    for i, amount in enumerate(grid):
        if amount <= 0.01:
            continue
        slot = slots[i]
        seconds = min(
            slot["e"] - slot["s"], math.ceil(amount / (estimate["charge_w"] * efficiency) * 60) * 60
        )
        # A partial window joins the next block's window; otherwise it starts
        # the block so a floor deadline is met.
        if i + 1 < len(grid) and grid[i + 1] > 0.01:
            s, e = slot["e"] - seconds, slot["e"]
        else:
            s, e = slot["s"], slot["s"] + seconds
        grid[i] = seconds / 3600 * estimate["charge_w"] * efficiency
        if windows and windows[-1][1] == s:
            windows[-1][1] = e
        else:
            windows.append([s, e])
    levels = trajectory()
    shortfall = (
        max(0.0, floor - TOLERANCE_WH - min(levels), target - TOLERANCE_WH - levels[-1])
        if levels
        else 0
    )
    return {
        "generated_at": tnow,
        "region": region,
        "signal": "co2_moer",
        "strategy": "adaptive",
        "windows": windows,
        "battery_pct": battery_pct,
        "target_pct": 100,
        "deadline": deadline,
        "floor_pct": floor_pct,
        "solar_day_wh": round(estimate["solar_day_wh"]),
        "solar_days": estimate["solar_days"],
        "load_w": round(estimate["load_w"], 1),
        "charge_w": round(estimate["charge_w"], 1),
        "grid_wh": round(sum(grid) / efficiency),
        "shortfall_wh": round(shortfall),
    }


def next_deadline(now: datetime) -> int:
    """The next 4 pm Pacific, when the peak starts and grid charging must end."""
    local = now.astimezone(PACIFIC)
    day = local.date() if local.hour < 16 else local.date() + timedelta(days=1)
    return int(datetime.combine(day, time(16), PACIFIC).timestamp())
