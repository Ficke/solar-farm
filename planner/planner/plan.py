"""Pick the cleanest grid windows from a marginal-emissions forecast."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def build_plan(
    points: list[tuple[datetime, float]],
    now: datetime,
    budget_hours: float = 4.0,
    block_minutes: int = 30,
    peak_hours: tuple[int, int] = (16, 21),
    region: str = "CAISO_NORTH",
) -> dict:
    """Return the plan.json the Shelly script follows.

    Forecast points are averaged into fixed blocks so the relay never flips
    more often than once per block. Blocks that start inside the PG&E peak
    (local time) or have already ended are dropped; the cleanest remaining
    blocks are taken until they cover ``budget_hours`` and merged into
    windows of unix timestamps.
    """
    block = timedelta(minutes=block_minutes)
    sums: dict[datetime, list[float]] = defaultdict(list)
    for t, value in points:
        start = _floor(t, block_minutes)
        sums[start].append(value)

    candidates = []
    for start, values in sums.items():
        end = start + block
        if end <= now:
            continue
        local_hour = start.astimezone(PACIFIC).hour
        if peak_hours[0] <= local_hour < peak_hours[1]:
            continue
        candidates.append((sum(values) / len(values), start))

    wanted = round(budget_hours * 60 / block_minutes)
    chosen = sorted(start for _, start in sorted(candidates)[:wanted])

    windows: list[list[int]] = []
    for start in chosen:
        s, e = int(start.timestamp()), int((start + block).timestamp())
        if windows and windows[-1][1] == s:
            windows[-1][1] = e
        else:
            windows.append([s, e])

    return {
        "generated_at": int(now.timestamp()),
        "region": region,
        "signal": "co2_moer",
        "windows": windows,
    }


def _floor(t: datetime, minutes: int) -> datetime:
    return t.replace(minute=t.minute - t.minute % minutes, second=0, microsecond=0)
