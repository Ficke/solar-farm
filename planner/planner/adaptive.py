"""Build greedy charging plans from observed battery, solar and load data."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, time, timedelta
from itertools import pairwise
from statistics import mean, median

from planner.battery import (
    AC_CHARGE,
    DISCHARGE,
    Battery,
    average_load_w,
    load_points,
    load_profile,
)
from planner.plan import PACIFIC

TIE_MOER = 50  # Round emissions to groups of this many lb/MWh.
MIN_SOLAR_WH = 150  # Reserve headroom when the solar allowance reaches this value.
MIN_CHARGE_W = 200  # Exclude low-power passthrough readings.
MIN_CHARGE_READINGS = 3
RECENT_CHARGE_READINGS = 30  # Favor recent charging speed over older readings.
TOLERANCE_WH = 30  # Ignore floor and target deficits below about 1%.
TAPER_PCT = 95  # The Jackery slows charging near full; keep those readings out of the rate.
FULL_PCT = 97  # At or above this, solar input is cut back and says little about the panels.


def estimates(
    samples: list[dict],
    now: int,
    solar_wh: float,
    load_w: float,
    charge_w: float,
    plug: list[dict] | None = None,
    battery: Battery | None = None,
) -> dict:
    """Estimate solar, load and AC charging from recent telemetry.

    Solar uses qualifying days among the last seven completed days; average
    load uses the last 24 hours. Both require six hours of coverage and
    exclude gaps over 15 minutes. ``load_profile`` averages the load in each
    15-minute slot of the day over the last week. Load comes from the
    battery's energy balance (solar and grid in, less the change in charge),
    because the Jackery's output reading lags and misses most of what is drawn.
    Grid energy and the charge rate come from the plug's own meter when its
    reports are given, else from the Jackery's AC input. Charging uses the
    latest 30 qualifying readings within a week. Insufficient coverage falls
    back to the supplied defaults.
    ``battery`` gives the measured capacity and solar reading scale.
    """
    samples = sorted({s["t"]: s for s in samples if s["t"] <= now}.values(), key=lambda s: s["t"])
    today = datetime.fromtimestamp(now, PACIFIC).date()
    first_day = today - timedelta(days=7)
    solar: dict[str, list[dict]] = defaultdict(list)
    load_energy = load_seconds = 0.0
    for s in samples:
        day = datetime.fromtimestamp(s["t"], PACIFIC).date()
        if first_day <= day < today and _finite(s, "solar_w"):
            solar[day.isoformat()].append(s)
    # A full battery cuts solar input back, so only intervals with room show
    # what the panels make; each 15-minute slot averages the days it had room.
    observed: dict[int, list[float]] = defaultdict(list)
    days = 0
    for points in solar.values():
        energy: dict[int, float] = defaultdict(float)
        seconds: dict[int, float] = defaultdict(float)
        daylight = 0.0
        for a, b in pairwise(points):
            if not 0 < b["t"] - a["t"] <= 900:
                continue
            local = datetime.fromtimestamp((a["t"] + b["t"]) // 2, PACIFIC)
            if 9 <= local.hour < 17:
                daylight += b["t"] - a["t"]
            if any(_finite(x, "battery_pct") and x["battery_pct"] >= FULL_PCT for x in (a, b)):
                continue
            quarter = local.hour * 4 + local.minute // 15
            energy[quarter] += (
                (max(0.0, a["solar_w"]) + max(0.0, b["solar_w"])) / 2 * (b["t"] - a["t"])
            )
            seconds[quarter] += b["t"] - a["t"]
        if daylight >= 6 * 3600:
            days += 1
            for quarter in range(96):
                if quarter in seconds:
                    observed[quarter].append(energy[quarter] / seconds[quarter])
                elif not 36 <= quarter < 68:
                    observed[quarter].append(0.0)  # Night readings are often missing.
    recent = [s for s in samples if now - 86400 <= s["t"] <= now]
    plug = sorted({r["t"]: r for r in plug or [] if r["t"] <= now}.values(), key=lambda r: r["t"])
    battery = battery or Battery()
    balance = average_load_w(recent, plug, battery)
    week = [s for s in samples if now - 7 * 86400 <= s["t"]]
    by_slot = load_profile(load_points(week, plug, battery), PACIFIC)
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
    default = {q: solar_wh / 8 if 36 <= q < 68 else 0.0 for q in range(96)}
    if days:
        # A daytime slot never seen with room keeps the configured estimate.
        shape = {q: mean(observed[q]) if observed[q] else default[q] for q in range(96)}
        good_day = sum(shape.values()) / 4
    else:
        good_day = solar_wh
        shape = default
    return {
        "solar_profile": shape,
        "solar_day_wh": good_day,
        "solar_days": days,
        "load_w": balance
        if balance is not None
        else load_energy / load_seconds
        if load_seconds >= 6 * 3600
        else load_w,
        "charge_w": median(charging) if len(charging) >= MIN_CHARGE_READINGS else charge_w,
        "battery": battery.to_dict(),
        "load_profile": by_slot,
    }


def _finite(s: dict, key: str) -> bool:
    return s.get(key) is not None and math.isfinite(s[key])


def build_adaptive_plan(
    points: list[tuple[datetime, float]],
    now: datetime,
    battery_pct: float,
    estimate: dict,
    floor_pct: float = 20,
    region: str = "CAISO_NORTH",
    hold: list[list[int]] | None = None,
) -> dict:
    """Target a full battery by the next 4 pm Pacific, outside peak hours.

    Charge in the cleanest 15-minute blocks; blocks within TIE_MOER of each
    other tie and the later one wins, so solar arrives first. Blocks in
    ``hold`` (the previous plan's current or next window) win ties, so small
    forecast changes don't move the relay. Room is kept for material later solar at
    half its estimated output. Once the battery is full and no room is kept,
    the plug also stays on to run the load from the grid whenever that emits
    less than draining the battery and recharging it later in the next block
    the plan would add. Unmet floor or target energy is reported as a
    shortfall.
    """
    tnow = int(now.timestamp())
    battery = Battery.from_dict(estimate.get("battery"))
    capacity = battery.capacity_wh
    floor = capacity * floor_pct / 100
    target = capacity
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
    # Slots never seen use the average load.
    loads = {int(q): w for q, w in (estimate.get("load_profile") or {}).items()}
    slots: list[dict] = []
    for start in range(tnow // 900 * 900, end, 900):
        s, e = max(tnow, start), min(end, start + 900)
        local = datetime.fromtimestamp(s, PACIFIC)
        hours = (e - s) / 3600
        solar = profile.get(local.hour * 4 + local.minute // 15, 0.0) * battery.solar_stored * hours
        moer = sum(signals[start]) / len(signals[start]) if start in signals else None
        load_w = loads.get(local.hour * 4 + local.minute // 15, estimate["load_w"])
        slots.append(
            {
                "s": s,
                "e": e,
                "solar": solar,
                "load": load_w * hours,  # Wh at the outlet
                "net": solar - load_w / DISCHARGE * hours,
                "max": estimate["charge_w"] * AC_CHARGE * hours,
                "moer": moer,
                "allowed": moer is not None and not 16 <= local.hour < 21,
            }
        )
    later = [0.0] * len(slots)
    for i in range(len(slots) - 2, -1, -1):
        later[i] = later[i + 1] + slots[i + 1]["solar"]
    keep = [h / 2 if h / 2 >= MIN_SOLAR_WH else 0.0 for h in later]
    initial = battery.wh(battery_pct)
    ranked = rank_blocks(slots, held_blocks(slots, hold or [], tnow))
    # Blocks where the plug stays on for the whole block to run the load.
    bypass: set[int] = set()
    recharge_at: dict[int, float] = {}  # rate used in each block's bypass test

    def trajectory(grid: list[float]) -> list[float]:
        level = initial
        out = []
        for i, slot in enumerate(slots):
            if i in bypass:
                # The grid runs the load and charges any room left at full rate.
                level = min(capacity, level + slot["solar"] + slot["max"])
            else:
                level = min(capacity, level + slot["net"] + grid[i])
            out.append(level)
        return out

    def charge() -> list[float]:
        grid = [0.0] * len(slots)
        order = [i for i in ranked if i not in bypass]

        def fill(by: int, desired: float) -> None:
            """Fill a deficit using only ranked blocks at or before ``by``."""
            for i in order:
                levels = trajectory(grid)
                need = desired - levels[by]
                if need <= TOLERANCE_WH:
                    break
                if i <= by:
                    # Only charge that is still stored at ``by`` helps: a block
                    # already followed by a full battery adds nothing.
                    room = min(capacity - level for level in levels[i : by + 1])
                    grid[i] += max(0.0, min(slots[i]["max"] - grid[i], need, room))

        for i in range(len(slots)):
            fill(i, floor)
        # Stop once a clean block can reach the ceiling reserved for later solar.
        for i in order:
            levels = trajectory(grid)
            before = levels[i - 1] if i else initial
            room = target - keep[i] - before - slots[i]["net"] - sum(grid[i:])
            grid[i] += max(0.0, min(slots[i]["max"] - grid[i], room))
            if grid[i] < slots[i]["max"] - 0.01:
                break
        # Cover any deadline deficit left by solar headroom or limited blocks.
        if slots:
            fill(len(slots) - 1, target)
        return grid

    grid = charge()
    for _ in range(len(slots)):
        levels = trajectory(grid)
        added = set()
        for i, slot in enumerate(slots):
            drain = -slot["net"]  # Wh the battery loses running the load
            before = levels[i - 1] if i else initial
            if (
                i in bypass
                or not slot["allowed"]
                or keep[i] > 0
                or drain <= 0
                or before < capacity - TOLERANCE_WH
            ):
                continue
            # The battery Wh used now come back later in the next block the
            # plan would add, at 1/AC_CHARGE grid Wh each.
            spare = [
                slots[j]["moer"]
                for j in ranked
                if j > i and j not in bypass and grid[j] < slots[j]["max"] - 0.01
            ]
            recharge = min(spare, default=math.inf)
            recharge_at[i] = recharge
            if slot["moer"] * slot["load"] <= recharge * drain / AC_CHARGE:
                added.add(i)
        if not added:
            break
        bypass |= added
        grid = charge()
    levels = trajectory(grid)
    windows: list[list[int]] = []
    drawn = 0.0  # Wh from the outlet
    for i, slot in enumerate(slots):
        if i in bypass:
            before = levels[i - 1] if i else initial
            stored = max(0.0, levels[i] - before - slot["solar"])
            s, e = slot["s"], slot["e"]
            drawn += slot["load"] + stored / AC_CHARGE
        elif grid[i] > 0.01:
            seconds = min(
                slot["e"] - slot["s"],
                math.ceil(grid[i] / (estimate["charge_w"] * AC_CHARGE) * 60) * 60,
            )
            # A partial window joins the next block's window; otherwise it
            # starts the block so a floor deadline is met.
            if i + 1 < len(slots) and (i + 1 in bypass or grid[i + 1] > 0.01):
                s, e = slot["e"] - seconds, slot["e"]
            else:
                s, e = slot["s"], slot["s"] + seconds
            grid[i] = seconds / 3600 * estimate["charge_w"] * AC_CHARGE
            drawn += grid[i] / AC_CHARGE
        else:
            continue
        if windows and windows[-1][1] == s:
            windows[-1][1] = e
        else:
            windows.append([s, e])
    levels = trajectory(grid)
    blocks = []
    for i, slot in enumerate(slots):
        local = datetime.fromtimestamp(slot["s"], PACIFIC)
        if slot["moer"] is None:
            mode = "none"
        elif 16 <= local.hour < 21:
            mode = "peak"
        elif i in bypass:
            mode = "bypass"
        elif grid[i] > 0.01:
            mode = "charge"
        elif keep[i] > 0:
            mode = "solar"
        else:
            mode = "battery"
        recharge = recharge_at.get(i)
        blocks.append(
            {
                "s": slot["s"],
                "e": slot["e"],
                "mode": mode,
                "moer": slot["moer"],
                "pct": round(levels[i] / capacity * 100, 1),
                "recharge": recharge if recharge is not None and math.isfinite(recharge) else None,
            }
        )
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
        "grid_wh": round(drawn),
        "bypass_wh": round(sum(slots[i]["load"] for i in bypass)),
        "blocks": blocks,
        "shortfall_wh": round(shortfall),
    }


def held_blocks(slots: list[dict], hold: list[list[int]], now: int) -> set[int]:
    """Slots overlapping the window in ``hold`` that is current or next at ``now``."""
    window = next((w for w in sorted(hold) if w[1] > now), None)
    if window is None:
        return set()
    return {i for i, slot in enumerate(slots) if slot["s"] < window[1] and window[0] < slot["e"]}


def rank_blocks(slots: list[dict], held: set[int]) -> list[int]:
    """Allowed slots, cleanest first.

    Slots within TIE_MOER of the cleanest slot not yet ranked tie. A held
    slot wins a tie, so another slot must be cleaner by more than TIE_MOER
    to replace it; otherwise the later slot wins.
    """
    order = sorted(
        (i for i, slot in enumerate(slots) if slot["allowed"]), key=lambda i: slots[i]["moer"]
    )
    ranked: list[int] = []
    while order:
        tied = [i for i in order if slots[i]["moer"] <= slots[order[0]]["moer"] + TIE_MOER]
        ranked += sorted(tied, key=lambda i: (i not in held, -slots[i]["s"]))
        order = [i for i in order if i not in tied]
    return ranked


def next_deadline(now: datetime) -> int:
    """Return the next 4 pm Pacific deadline in Unix seconds."""
    local = now.astimezone(PACIFIC)
    day = local.date() if local.hour < 16 else local.date() + timedelta(days=1)
    return int(datetime.combine(day, time(16), PACIFIC).timestamp())
