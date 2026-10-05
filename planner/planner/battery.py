"""Measure the battery's usable capacity and the solar reading's scale.

The Jackery reports charge in whole percent and solar from its own sensor.
Between two readings where the charge changes, the battery gained exactly
that many percent. Over spans where only the plug charges it, the plug's
meter times the charger efficiency gives Wh per percent, which tracks
capacity as the battery ages. Over sunny spans with the plug off, that
capacity times the gain, divided by the solar charge efficiency, gives the
panel's true output per Wh the sensor reports. Charger and inverter
efficiencies can't be separated from capacity without a meter on the
output, so they are assumed.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import asdict, dataclass
from itertools import pairwise

from planner.telemetry import CAPACITY_WH

AC_CHARGE = 0.9  # Wh stored per Wh the plug meters.
SOLAR_CHARGE = 0.95  # Wh stored per Wh the panel makes; the DC charger skips a conversion.
DISCHARGE = 0.9  # Wh at the outlet per Wh drawn from the battery.
MIN_GAIN_PCT = 5  # Percent of charge gained before a measurement replaces the default.
MIN_CHARGE_W = 200  # Plug power that means the Jackery is charging.
MIN_SOLAR_W = 10  # Average solar reading for a span to count as sunny.
FULL_PCT = 97  # At or above this, the Jackery cuts solar input back.
MAX_SPAN = 3 * 3600  # Longest span between charge changes to measure across.
CAPACITY_RANGE = (0.5 * CAPACITY_WH, 1.1 * CAPACITY_WH)  # Outside this, a reading is wrong.
SCALE_RANGE = (0.5, 3.0)


@dataclass(frozen=True)
class Battery:
    capacity_wh: float = CAPACITY_WH  # usable Wh from 0 to 100%
    solar_scale: float = 1.0  # panel Wh per Wh of the Jackery's solar reading

    @property
    def solar_stored(self) -> float:
        """Wh stored per Wh of solar reading."""
        return self.solar_scale * SOLAR_CHARGE

    def wh(self, pct: float) -> float:
        return pct / 100 * self.capacity_wh

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> Battery:
        return cls(
            **{k: float(v) for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        )


def integral(points: list[tuple[int, float]]) -> Callable[[float], float]:
    """Return cumulative Wh from the first point, interpolating between points."""
    times = [t for t, _ in points]
    sums = [0.0]
    for (t0, w0), (t1, w1) in pairwise(points):
        sums.append(sums[-1] + (w0 + w1) / 2 * (t1 - t0) / 3600)

    def at(t: float) -> float:
        i = bisect_right(times, t) - 1
        if i < 0:
            return 0.0
        if i >= len(points) - 1:
            return sums[-1]
        (t0, w0), (t1, w1) = points[i], points[i + 1]
        w = w0 + (w1 - w0) * (t - t0) / (t1 - t0)
        return sums[i] + (w0 + w) / 2 * (t - t0) / 3600

    return at


def measure(samples: list[dict], plug: list[dict], previous: Battery | None = None) -> Battery:
    """Measure from readings and plug reports; keep ``previous`` for what they can't show."""
    previous = previous or Battery()
    readings = sorted((s for s in samples if _finite(s, "battery_pct")), key=lambda s: s["t"])
    changes = [b for a, b in pairwise(readings) if b["battery_pct"] != a["battery_pct"]]
    reports = sorted((r for r in plug if _finite(r, "w")), key=lambda r: r["t"])
    report_times = [r["t"] for r in reports]
    grid = integral([(r["t"], max(0.0, r["w"])) for r in reports])
    solar = integral(
        [
            (s["t"], max(0.0, s["solar_w"]))
            for s in sorted(samples, key=lambda s: s["t"])
            if _finite(s, "solar_w")
        ]
    )
    ac_wh = ac_pct = solar_wh = solar_pct = 0.0
    for a, b in pairwise(changes):
        gain = b["battery_pct"] - a["battery_pct"]
        if gain <= 0 or not 0 < b["t"] - a["t"] <= MAX_SPAN:
            continue
        inside = reports[bisect_right(report_times, a["t"]) : bisect_right(report_times, b["t"])]
        grid_wh, solar_read = grid(b["t"]) - grid(a["t"]), solar(b["t"]) - solar(a["t"])
        if inside and all(r["w"] >= MIN_CHARGE_W for r in inside) and solar_read < 0.1 * grid_wh:
            ac_wh += grid_wh
            ac_pct += gain
        elif (
            grid_wh < 1
            and b["battery_pct"] < FULL_PCT
            and solar_read / (b["t"] - a["t"]) * 3600 >= MIN_SOLAR_W
        ):
            solar_wh += solar_read
            solar_pct += gain
    capacity = previous.capacity_wh
    if ac_pct >= MIN_GAIN_PCT:
        capacity = _clamp(AC_CHARGE * ac_wh / ac_pct * 100, CAPACITY_RANGE)
    scale = previous.solar_scale
    if solar_pct >= MIN_GAIN_PCT and solar_wh > 0:
        # Load during these spans lowers the gain, so this can only understate.
        scale = _clamp(capacity * solar_pct / 100 / SOLAR_CHARGE / solar_wh, SCALE_RANGE)
    return Battery(capacity_wh=capacity, solar_scale=scale)


def _finite(s: dict, key: str) -> bool:
    return s.get(key) is not None and math.isfinite(s[key])


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])
