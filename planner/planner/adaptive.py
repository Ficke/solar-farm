"""Plan grid charging from the battery level, expected solar and the rate timeline."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, time, timedelta
from itertools import pairwise
from statistics import mean, median

from planner.battery import AC_CHARGE, Battery
from planner.plan import PACIFIC

# Actual rates sit near 0 or above 800 lb/MWh; forecasts up to this mostly come true as 0.
CLEAN_MOER = 300
CHARGE_MARGIN = 900  # Seconds before the deadline that charging ends, for a slow charge.
# Dirty forecasts miss the actual by a median 35 and 75th percentile 92 lb/MWh.
DIRTY_TIE = 100
START_WH = 100  # Smallest target deficit that starts a charge; about 3%.
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
    charge_w: float,
    plug: list[dict] | None = None,
    battery: Battery | None = None,
) -> dict:
    """Estimate solar and AC charging from recent telemetry.

    Solar uses qualifying days among the last seven completed days with six
    hours of daytime coverage, excluding gaps over 15 minutes. The charge rate
    comes from the plug's own meter when its reports are given, else from the
    Jackery's AC input, and uses the latest 30 qualifying readings within a
    week. Insufficient coverage falls back to the supplied defaults.
    ``battery`` gives the measured capacity and solar reading scale.
    """
    samples = sorted({s["t"]: s for s in samples if s["t"] <= now}.values(), key=lambda s: s["t"])
    today = datetime.fromtimestamp(now, PACIFIC).date()
    first_day = today - timedelta(days=7)
    solar: dict[str, list[dict]] = defaultdict(list)
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
    plug = sorted({r["t"]: r for r in plug or [] if r["t"] <= now}.values(), key=lambda r: r["t"])
    battery = battery or Battery()
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
        "charge_w": median(charging) if len(charging) >= MIN_CHARGE_READINGS else charge_w,
        "battery": battery.to_dict(),
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
    charging: bool = False,
) -> dict:
    """Put the grid charge needed by the next 4 pm Pacific into the cleanest blocks.

    ``points`` is the rate timeline: the live rate for the current block and
    the forecast after it. The need is the 4 pm target (full, less the next
    day's solar) less the battery now and the solar expected before then, so
    room for solar is left by construction. Allowed 15-minute blocks are
    outside 4-9 pm and end CHARGE_MARGIN before the deadline; rank_blocks
    orders them. The need fills down that order, after any gap below the
    floor. The current block's charge is the plug decision. The plan projects
    no load: each replan starts from the latest reading. A full battery in a
    clean block with no solar left to make room for, today or tomorrow, keeps
    the plug on, so loads run on the clean grid. Unmet floor or target energy is reported as
    a shortfall. Unless ``charging`` (the previous plan charges now), a
    target deficit under START_WH waits, so whole-percent readings don't
    cycle the relay.
    """
    tnow = int(now.timestamp())
    battery = Battery.from_dict(estimate.get("battery"))
    capacity = battery.capacity_wh
    floor = capacity * floor_pct / 100
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
    # Solar between this deadline and the next one fills the room left here.
    tomorrow = sum(profile.values()) / 4 * battery.solar_stored
    target = max(floor, capacity - (tomorrow if tomorrow > TOLERANCE_WH else 0.0))
    slots: list[dict] = []
    for start in range(tnow // 900 * 900, end, 900):
        s, e = max(tnow, start), min(end, start + 900)
        local = datetime.fromtimestamp(s, PACIFIC)
        hours = (e - s) / 3600
        solar = profile.get(local.hour * 4 + local.minute // 15, 0.0) * battery.solar_stored * hours
        moer = sum(signals[start]) / len(signals[start]) if start in signals else None
        peak = 16 <= local.hour < 21
        slots.append(
            {
                "s": s,
                "e": e,
                "solar": solar,
                "max": estimate["charge_w"] * AC_CHARGE * hours,
                "moer": moer,
                "peak": peak,
                "allowed": moer is not None and not peak and e <= deadline - CHARGE_MARGIN,
            }
        )
    later = [0.0] * len(slots)
    for i in range(len(slots) - 2, -1, -1):
        later[i] = later[i + 1] + slots[i + 1]["solar"]
    initial = battery.wh(battery_pct)
    order = rank_blocks(slots)

    def trajectory(grid: list[float]) -> list[float]:
        level = initial
        out = []
        for slot, g in zip(slots, grid, strict=True):
            level = min(capacity, level + slot["solar"] + g)
            out.append(level)
        return out

    grid = [0.0] * len(slots)

    def fill(by: int, desired: float) -> None:
        """Fill a deficit at ``by`` down the ranking, from blocks at or before it."""
        for i in order:
            levels = trajectory(grid)
            need = desired - levels[by]
            if need <= TOLERANCE_WH:
                break
            if i <= by:
                # Only charge still stored at ``by`` helps: charge followed by
                # a full battery adds nothing.
                room = min(capacity - level for level in levels[i : by + 1])
                grid[i] += max(0.0, min(slots[i]["max"] - grid[i], need, room))

    for i in range(len(slots)):
        fill(i, floor)
    slack = TOLERANCE_WH if charging else START_WH
    if slots and target - trajectory(grid)[-1] > slack:
        fill(len(slots) - 1, target)
    levels = trajectory(grid)
    bypass = set()
    for i, slot in enumerate(slots):
        before = levels[i - 1] if i else initial
        if (
            slot["moer"] is not None
            and slot["moer"] <= CLEAN_MOER
            and not slot["peak"]
            and before >= capacity - TOLERANCE_WH
            and slot["solar"] + later[i] <= TOLERANCE_WH
            and target >= capacity - TOLERANCE_WH
        ):
            bypass.add(i)
    windows: list[list[int]] = []
    drawn = 0.0  # Wh from the outlet
    for i, slot in enumerate(slots):
        if i in bypass:
            s, e = slot["s"], slot["e"]
            drawn += grid[i] / AC_CHARGE
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
        before = levels[i - 1] if i else initial
        if slot["moer"] is None:
            mode = "none"
        elif slot["peak"]:
            mode = "peak"
        elif i in bypass:
            mode = "bypass"
        elif grid[i] > 0.01:
            mode = "charge"
        elif (
            slot["moer"] <= CLEAN_MOER
            and slot["allowed"]
            and before < capacity - TOLERANCE_WH
            and later[i] > TOLERANCE_WH
        ):
            mode = "solar"  # clean, with room left for the solar still to come
        else:
            mode = "battery"
        blocks.append(
            {
                "s": slot["s"],
                "e": slot["e"],
                "mode": mode,
                "moer": slot["moer"],
                "pct": round(levels[i] / capacity * 100, 1),
            }
        )
    shortfall = (
        max(0.0, floor - TOLERANCE_WH - min(levels), target - slack - levels[-1]) if levels else 0
    )
    return {
        "generated_at": tnow,
        "region": region,
        "signal": "co2_moer",
        "strategy": "adaptive",
        "windows": windows,
        "battery_pct": battery_pct,
        "target_pct": round(target / capacity * 100, 1),
        "deadline": deadline,
        "floor_pct": floor_pct,
        "solar_day_wh": round(estimate["solar_day_wh"]),
        "solar_days": estimate["solar_days"],
        "charge_w": round(estimate["charge_w"], 1),
        "grid_wh": round(drawn),
        "blocks": blocks,
        "shortfall_wh": round(shortfall),
    }


def rank_blocks(slots: list[dict]) -> list[int]:
    """Allowed slots in the order they take charge.

    Clean slots (CLEAN_MOER or less) come first, earliest first: they emit
    about nothing whenever they run, and early charge is usable sooner and
    doesn't wait on a later forecast. Dirty slots follow, cleanest first.
    Dirty slots within DIRTY_TIE of the cleanest one left tie, and the later
    one wins: the gap is within forecast error, and waiting leaves time for a
    clean slot to appear.
    """
    allowed = [i for i, slot in enumerate(slots) if slot["allowed"]]
    clean = [i for i in allowed if slots[i]["moer"] <= CLEAN_MOER]
    left = sorted((i for i in allowed if i not in clean), key=lambda i: slots[i]["moer"])
    dirty: list[int] = []
    while left:
        tied = [i for i in left if slots[i]["moer"] <= slots[left[0]]["moer"] + DIRTY_TIE]
        dirty += sorted(tied, key=lambda i: -slots[i]["s"])
        left = [i for i in left if i not in tied]
    return clean + dirty


def next_deadline(now: datetime) -> int:
    """Return the next 4 pm Pacific deadline in Unix seconds."""
    local = now.astimezone(PACIFIC)
    day = local.date() if local.hour < 16 else local.date() + timedelta(days=1)
    return int(datetime.combine(day, time(16), PACIFIC).timestamp())
