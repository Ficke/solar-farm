"""Append Jackery readings to a CSV and turn them into a reserve recommendation."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from planner.jackery import Reading
from planner.plan import PACIFIC

FIELDS = ["time", "battery_pct", "solar_w", "ac_input_w", "output_w", "raw"]
CAPACITY_WH = 3072  # Explorer 3000 v2


def append(path: Path, r: Reading) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(
            {
                "time": r.time.isoformat(),
                "battery_pct": r.battery_pct,
                "solar_w": r.solar_w,
                "ac_input_w": r.ac_input_w,
                "output_w": r.output_w,
                "raw": json.dumps(r.raw, separators=(",", ":")),
            }
        )


def load(path: Path) -> list[tuple[datetime, float]]:
    rows = []
    with path.open() as f:
        for row in csv.DictReader(f):
            if row["solar_w"] in ("", "None"):
                continue
            rows.append((datetime.fromisoformat(row["time"]), float(row["solar_w"])))
    return sorted(rows)


def daily_solar_wh(samples: list[tuple[datetime, float]], min_samples: int = 36) -> dict:
    """Integrate solar watts per local day; skip days with too few samples."""
    by_day: dict = defaultdict(list)
    for t, w in samples:
        by_day[t.astimezone(PACIFIC).date()].append((t, w))
    out = {}
    max_gap = timedelta(hours=1)
    for day, pts in by_day.items():
        if len(pts) < min_samples:
            continue
        wh = 0.0
        for (t0, w0), (t1, w1) in zip(pts, pts[1:]):
            gap = min(t1 - t0, max_gap)
            wh += (w0 + w1) / 2 * gap.total_seconds() / 3600
        out[day] = wh
    return out


def recommend_reserve(daily_wh: dict, days: int = 14, capacity_wh: int = CAPACITY_WH) -> dict:
    """Reserve that leaves room for a good solar day (80th percentile)."""
    recent = [daily_wh[d] for d in sorted(daily_wh)[-days:]]
    if not recent:
        return {"reserve_pct": None, "days": 0}
    recent.sort()
    good_day = recent[min(len(recent) - 1, int(round(0.8 * (len(recent) - 1))))]
    headroom = good_day / capacity_wh * 100
    reserve = 5 * round((100 - headroom) / 5)
    return {
        "reserve_pct": max(10, min(90, reserve)),
        "good_day_wh": round(good_day),
        "days": len(recent),
    }
