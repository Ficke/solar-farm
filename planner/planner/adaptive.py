"""Build greedy charging plans from observed battery, solar and load data."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, time, timedelta
from itertools import pairwise
from statistics import mean, median

from planner.plan import PACIFIC
from planner.telemetry import CAPACITY_WH

TIE_MOER = 50  # Round emissions to groups of this many lb/MWh.
MIN_SOLAR_WH = 150  # Reserve headroom when the solar allowance reaches this value.
MIN_CHARGE_W = 200  # Exclude low-power passthrough readings.
MIN_CHARGE_READINGS = 3
RECENT_CHARGE_READINGS = 30  # Favor recent charging speed over older readings.
TOLERANCE_WH = 30  # Ignore floor and target deficits below about 1%.
EFFICIENCY = 0.9  # Each way through the battery's charger and inverter.
TAPER_PCT = 95  # The Jackery slows charging near full; keep those readings out of the rate.


def estimates(
    samples: list[dict],
    now: int,
    solar_wh: float,
    load_w: float,
    charge_w: float,
    plug: list[dict] | None = None,
) -> dict:
    """Estimate solar, load and AC charging from recent telemetry.

    Solar uses qualifying days among the last seven completed days; load uses
    the last 24 hours. Both require six hours of coverage and exclude gaps
    over 15 minutes. Load comes from the battery's energy balance (solar and
    grid in, less the change in charge), because the Jackery's output reading
    lags and misses most of what is drawn. Grid energy and the charge rate
    come from the plug's own meter when its reports are given, else from the
    Jackery's AC input. Charging uses the latest 30 qualifying readings within
    a week. Insufficient coverage falls back to the supplied defaults.
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
    plug = sorted({r["t"]: r for r in plug or [] if r["t"] <= now}.values(), key=lambda r: r["t"])
    balance = load_from_balance(recent, plug)
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
    if plug:
        # Wall power while the plug is on, away from the slow charge near full.
        times = [s["t"] for s in samples]
        charging = []
        for r in plug:
            w = r.get("w")
            if r["t"] < now - 7 * 86400 or not r.get("on") or w is None or not math.isfinite(w):
                continue
            i = bisect_right(times, r["t"]) - 1
            pct = samples[i].get("battery_pct") if i >= 0 else None
            if w >= MIN_CHARGE_W and (pct is None or pct < TAPER_PCT):
                charging.append(w)
    else:
        charging = [
            w
            for s in samples
            if now - 7 * 86400 <= s["t"]
            and s.get("ac_input_w") is not None
            and math.isfinite(s["ac_input_w"])
            and math.isfinite(s.get("output_w") or 0.0)
            and (w := s["ac_input_w"] - max(0.0, s.get("output_w") or 0.0)) >= MIN_CHARGE_W
        ]
    charging = charging[-RECENT_CHARGE_READINGS:]
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
        "load_w": balance
        if balance is not None
        else load_energy / load_seconds
        if load_seconds >= 6 * 3600
        else load_w,
        "charge_w": median(charging) if len(charging) >= MIN_CHARGE_READINGS else charge_w,
    }


def _finite(s: dict, key: str) -> bool:
    return s.get(key) is not None and math.isfinite(s[key])


def load_from_balance(samples: list[dict], plug: list[dict]) -> float | None:
    """Average AC load over the samples from energy in and the change in charge.

    Over each stretch of readings without a gap over 15 minutes, what went
    into the battery (solar and grid, less charging losses) minus what it
    gained is what the load drew from it, less inverter losses. Grid energy
    is the plug meter's increase when ``plug`` reports are given, else the
    Jackery's AC input. One percent of charge is 31 Wh, so this needs six
    hours of readings to be useful.
    """
    readings = [s for s in samples if _finite(s, "battery_pct")]
    stretches: list[list[dict]] = []
    for s in readings:
        if stretches and 0 < s["t"] - stretches[-1][-1]["t"] <= 900:
            stretches[-1].append(s)
        else:
            stretches.append([s])
    drawn = seconds = 0.0
    for run in stretches:
        if len(run) < 2:
            continue
        a, b = run[0]["t"], run[-1]["t"]
        solar = sum(
            (max(0.0, x["solar_w"]) + max(0.0, y["solar_w"])) / 2 * (y["t"] - x["t"]) / 3600
            for x, y in pairwise(run)
            if _finite(x, "solar_w") and _finite(y, "solar_w")
        )
        if plug:
            grid = 0.0
            for x, y in pairwise(r for r in plug if a <= r["t"] <= b):
                if not 0 < y["t"] - x["t"] <= 900:
                    continue
                if _finite(x, "wh") and _finite(y, "wh") and y["wh"] >= x["wh"]:
                    grid += y["wh"] - x["wh"]  # the meter's running total
                elif _finite(x, "w") and _finite(y, "w"):
                    grid += (max(0.0, x["w"]) + max(0.0, y["w"])) / 2 * (y["t"] - x["t"]) / 3600
        else:
            grid = sum(
                (max(0.0, x["ac_input_w"]) + max(0.0, y["ac_input_w"]))
                / 2
                * (y["t"] - x["t"])
                / 3600
                for x, y in pairwise(run)
                if _finite(x, "ac_input_w") and _finite(y, "ac_input_w")
            )
        gained = (run[-1]["battery_pct"] - run[0]["battery_pct"]) / 100 * CAPACITY_WH
        drawn += (solar + grid) * EFFICIENCY - gained
        seconds += b - a
    if seconds < 6 * 3600:
        return None
    return max(0.0, drawn * EFFICIENCY / (seconds / 3600))


def build_adaptive_plan(
    points: list[tuple[datetime, float]],
    now: datetime,
    battery_pct: float,
    estimate: dict,
    floor_pct: float = 20,
    efficiency: float = EFFICIENCY,
    region: str = "CAISO_NORTH",
) -> dict:
    """Target a full battery by the next 4 pm Pacific, outside peak hours.

    Rank 15-minute blocks by rounded emissions groups, preferring later ties
    so solar arrives first. Reserve room for material later solar at half
    its estimated output. Report unmet floor or target energy as a shortfall.
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
        """Fill a deficit using only ranked blocks at or before ``by``."""
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
    # Stop once a clean block can reach the ceiling reserved for later solar.
    for i in ranked:
        levels = trajectory()
        before = levels[i - 1] if i else initial
        room = target - keep[i] - before - slots[i]["net"] - sum(grid[i:])
        grid[i] += max(0.0, min(slots[i]["max"] - grid[i], room))
        if grid[i] < slots[i]["max"] - 0.01:
            break
    # Cover any deadline deficit left by solar headroom or limited blocks.
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
    """Return the next 4 pm Pacific deadline in Unix seconds."""
    local = now.astimezone(PACIFIC)
    day = local.date() if local.hour < 16 else local.date() + timedelta(days=1)
    return int(datetime.combine(day, time(16), PACIFIC).timestamp())
