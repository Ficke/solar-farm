"""Model the battery: its capacity, the solar reading's scale, and the energy balance.

Every estimate of energy into and out of the battery goes through ``Flows``:
the planner's average load, the daily totals and CO2, the Power chart's load
line, and the capacity and solar-scale measurements.

The Jackery reports charge in whole percent and solar from its own sensor.
Its output reading lags and misses most draws, so the load is what came in
(solar, and grid from the plug's meter) less what the charge gained.

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
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import asdict, dataclass
from itertools import pairwise

from planner.telemetry import CAPACITY_WH

AC_CHARGE = 0.9  # Wh stored per Wh the plug meters.
SOLAR_CHARGE = 0.95  # Wh stored per Wh the panel makes; the DC charger skips a conversion.
DISCHARGE = 0.9  # Wh at the outlet per Wh drawn from the battery.
# Percent of charge gained before a measurement replaces the previous one. Each
# end of a span is known to a minute, about 17 Wh at 1 kW, so short totals are noisy.
MIN_CAPACITY_PCT = 15
MIN_SOLAR_PCT = 10
WINDOW = 30 * 86400  # Readings to measure across; capacity fades over months.
MIN_CHARGE_W = 200  # Plug power that means the Jackery is charging.
MIN_SOLAR_W = 10  # Average solar reading for a span to count as sunny.
FULL_PCT = 97  # At or above this, the Jackery cuts solar input back.
MAX_SPAN = 3 * 3600  # Longest span between charge changes to measure across.
CAPACITY_RANGE = (0.5 * CAPACITY_WH, 1.1 * CAPACITY_WH)  # Outside this, a reading is wrong.
SCALE_RANGE = (0.5, 3.0)
MAX_GAP = 3600  # Cap each integration interval at one hour.
MIN_SPAN = 600  # Seconds; see spans().
STEADY = 1.25  # Largest ratio between runtime-based draws in a joined span.

type Rate = Callable[[float], float | None]  # Marginal CO2 in lb/MWh at a time.


def no_rate(_t: float) -> float | None:
    return None


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


def series(items: list[dict], key: str) -> list[tuple[int, float]]:
    return sorted((int(i["t"]), float(i[key])) for i in items if _finite(i, key))


def energy(points: list[tuple[int, float]], rate: Rate = no_rate) -> tuple[float, float]:
    """Integrate Wh and CO2 in lb, using interval-midpoint rates and capped gaps."""
    wh = lb = 0.0
    for (t0, w0), (t1, w1) in pairwise(points):
        seg = (w0 + w1) / 2 * min(t1 - t0, MAX_GAP) / 3600
        wh += seg
        r = rate((t0 + t1) / 2)
        if r is not None:
            lb += seg * r / 1e6
    return wh, lb


def integrate_wh(points: list[tuple[int, float]]) -> float:
    return energy(points)[0]


def cumulative(
    points: list[tuple[int, float]], rate: Rate = no_rate
) -> Callable[[float], tuple[float, float]]:
    """Return cumulative Wh and CO2 in lb from the first point to a given time."""
    times = [t for t, _ in points]
    sums = [(0.0, 0.0)]
    for a, b in pairwise(points):
        wh, lb = energy([a, b], rate)
        sums.append((sums[-1][0] + wh, sums[-1][1] + lb))

    def at(t: float) -> tuple[float, float]:
        i = bisect_right(times, t) - 1
        if i < 0:
            return 0.0, 0.0
        if i >= len(points) - 1 or t <= times[i]:
            return sums[i]
        (t0, w0), (t1, w1) = points[i], points[i + 1]
        w = w0 + (w1 - w0) * (t - t0) / (t1 - t0)
        wh, lb = energy([(t0, w0), (int(t), w)], rate)
        return sums[i][0] + wh, sums[i][1] + lb

    return at


def metered(reports: list[dict], rate: Rate = no_rate) -> Callable[[float], tuple[float, float]]:
    """Return cumulative grid Wh and CO2 in lb from the plug's reports to a given time.

    Each interval uses the meter's running total (``wh``) when it rose within
    15 minutes, else the average of the two power readings.
    """
    points = sorted((r for r in reports if _finite(r, "w")), key=lambda r: r["t"])
    times = [r["t"] for r in points]
    sums = [(0.0, 0.0)]
    for x, y in pairwise(points):
        if _finite(x, "wh") and _finite(y, "wh") and y["wh"] >= x["wh"] and y["t"] - x["t"] <= 900:
            wh = y["wh"] - x["wh"]
        else:
            wh = integrate_wh([(x["t"], max(0.0, x["w"])), (y["t"], max(0.0, y["w"]))])
        r = rate((x["t"] + y["t"]) / 2)
        sums.append((sums[-1][0] + wh, sums[-1][1] + (wh * r / 1e6 if r is not None else 0.0)))

    def at(t: float) -> tuple[float, float]:
        i = bisect_right(times, t) - 1
        if i < 0:
            return 0.0, 0.0
        if i >= len(points) - 1 or t <= times[i]:
            return sums[i]
        f = (t - times[i]) / (times[i + 1] - times[i])
        (wh0, lb0), (wh1, lb1) = sums[i], sums[i + 1]
        return wh0 + (wh1 - wh0) * f, lb0 + (lb1 - lb0) * f

    return at


@dataclass(frozen=True)
class Balance:
    """Energy in and out of the battery between two readings."""

    load: float  # Wh at the outlets
    direct: float  # Wh of the load supplied straight from the plug
    solar_read: float  # Wh of the Jackery's solar reading
    solar_in: float  # Solar Wh stored
    grid_wh: float
    grid_lb: float
    share: float  # Share of the time the plug supplied power


class Flows:
    """Energy into and out of the battery, from readings and the plug's meter.

    Grid energy comes from the plug's meter, or without plug reports, from the
    Jackery's AC input reading.
    """

    def __init__(
        self, samples: list[dict], plug: list[dict], battery: Battery, rate: Rate = no_rate
    ) -> None:
        self.battery = battery
        self.solar = cumulative([(t, max(0.0, w)) for t, w in series(samples, "solar_w")])
        if not plug:
            plug = [{"t": t, "w": w} for t, w in series(samples, "ac_input_w")]
        self.grid = metered(plug, rate)
        # Integrating 1 W while the plug draws power gives hours supplied.
        self.supplied = cumulative([(t, 1.0 if w > 0 else 0.0) for t, w in series(plug, "w")])
        readings = sorted((s for s in samples if _finite(s, "battery_pct")), key=lambda s: s["t"])
        self.draw = [(s["t"], _draw(s)) for s in readings]
        self.draw_times = [t for t, _ in self.draw]

    def between(self, a: dict, b: dict) -> Balance:
        """Balance energy from reading ``a`` to reading ``b``.

        While the plug supplies power, the Jackery passes it to the load first
        and charges with the rest, so that share of the time runs the load at
        the charger's efficiency instead of the inverter's.
        """
        t0, t1 = a["t"], b["t"]
        solar_read = self.solar(t1)[0] - self.solar(t0)[0]
        (g1, g1_lb), (g0, g0_lb) = self.grid(t1), self.grid(t0)
        grid_wh, grid_lb = g1 - g0, g1_lb - g0_lb
        hours = self.supplied(t1)[0] - self.supplied(t0)[0]
        share = min(1.0, hours * 3600 / (t1 - t0)) if t1 > t0 else 0.0
        gained = self.battery.wh(b["battery_pct"] - a["battery_pct"])
        solar_in = solar_read * self.battery.solar_stored
        load = (solar_in + grid_wh * AC_CHARGE - gained) / (
            share * AC_CHARGE + (1 - share) / DISCHARGE
        )
        direct = load * share
        if direct > grid_wh:
            direct = grid_wh
            load = grid_wh + (solar_in - gained) * DISCHARGE
        if load <= 0:
            # More charge than measured input, usually from a low solar reading.
            load = direct = 0.0
        return Balance(load, direct, solar_read, solar_in, grid_wh, grid_lb, share)

    def steady(self, t0: int, t1: int) -> bool:
        """Whether the plug stayed off and runtime estimates show a steady draw."""
        if self.supplied(t1)[0] != self.supplied(t0)[0] or self.timing(t0, t1) is None:
            return False
        i = bisect_right(self.draw_times, t0) - 1
        ws = [w for _, w in self.draw[i : bisect_right(self.draw_times, t1 - 1)] if w]
        return bool(ws) and max(ws) <= STEADY * min(ws)

    def timing(self, t0: int, t1: int) -> Callable[[float], float] | None:
        """Return the share of a span's load drawn by each time, or None without estimates."""
        i = bisect_right(self.draw_times, t0) - 1
        j = bisect_right(self.draw_times, t1 - 1)
        steps = self.draw[max(i, 0) : j]
        if i < 0 or any(w is None for _, w in steps):
            return None
        cuts = [t0] + [t for t, _ in steps[1:]] + [t1]
        sums = [0.0]
        for (t, u), (_, w) in zip(pairwise(cuts), steps, strict=True):
            sums.append(sums[-1] + (w or 0.0) * (u - t))
        total = sums[-1]
        if total <= 0:
            return None

        def done(t: float) -> float:
            if t <= t0:
                return 0.0
            if t >= t1:
                return 1.0
            k = bisect_right(cuts, t) - 1
            w = steps[k][1] or 0.0
            return (sums[k] + w * (t - cuts[k])) / total

        return done


@dataclass
class Span:
    """Load between two readings where the charge changed."""

    t0: int
    t1: int
    pct: float  # Charge at the end.
    load: float  # Wh
    direct: float  # Wh supplied straight from the plug
    solar_in: float  # Solar Wh stored
    grid_wh: float
    grid_lb: float
    done: Callable[[float], float]  # Share of the load drawn by a given time.


def spans(
    samples: list[dict], plug: list[dict], battery: Battery, rate: Rate = no_rate
) -> list[Span]:
    """Split the load by whole-percent charge changes.

    Charge readings are whole percent (about 31 Wh), so the balance runs
    between readings where the charge changes. Within each span, the load
    follows the Jackery's runtime estimate: charge divided by hours left is
    proportional to the draw. Spans without that estimate, or where the plug
    supplies power, spread the load evenly.
    """
    readings = sorted((s for s in samples if _finite(s, "battery_pct")), key=lambda s: s["t"])
    if len(readings) < 2:
        return []
    flows = Flows(samples, plug, battery, rate)
    steps = [readings[0]]
    steps += [b for a, b in pairwise(readings) if b["battery_pct"] != a["battery_pct"]]
    if steps[-1] is not readings[-1]:
        steps.append(readings[-1])
    # Whole-percent steps a minute or two apart alternate between double and
    # half the real draw. While runtime estimates show a steady draw, join
    # steps into spans of at least MIN_SPAN.
    edges = [steps[0]]
    for k, e in enumerate(steps[1:-1], 1):
        if e["t"] - edges[-1]["t"] >= MIN_SPAN or not flows.steady(
            edges[-1]["t"], steps[k + 1]["t"]
        ):
            edges.append(e)
    edges.append(steps[-1])
    out = []
    for a, b in pairwise(edges):
        t0, t1 = a["t"], b["t"]
        if t1 <= t0:
            continue
        bal = flows.between(a, b)
        done = flows.timing(t0, t1) if bal.share == 0 else None
        out.append(
            Span(
                t0,
                t1,
                float(b["battery_pct"]),
                bal.load,
                bal.direct,
                bal.solar_in,
                bal.grid_wh,
                bal.grid_lb,
                done or (lambda t, t0=t0, t1=t1: min(1.0, max(0.0, (t - t0) / (t1 - t0)))),
            )
        )
    return out


def average_load_w(samples: list[dict], plug: list[dict], battery: Battery) -> float | None:
    """Average load over the samples, from the balance across each stretch of readings.

    Stretches end at gaps over 15 minutes. One percent of charge is about
    31 Wh, so this needs six hours of readings to be useful.
    """
    readings = sorted((s for s in samples if _finite(s, "battery_pct")), key=lambda s: s["t"])
    stretches: list[list[dict]] = []
    for s in readings:
        if stretches and 0 < s["t"] - stretches[-1][-1]["t"] <= 900:
            stretches[-1].append(s)
        else:
            stretches.append([s])
    flows = Flows(samples, plug, battery)
    wh = seconds = 0.0
    for run in stretches:
        if len(run) >= 2:
            wh += flows.between(run[0], run[-1]).load
            seconds += run[-1]["t"] - run[0]["t"]
    return wh / (seconds / 3600) if seconds >= 6 * 3600 else None


def measure(samples: list[dict], plug: list[dict], previous: Battery | None = None) -> Battery:
    """Measure from readings and plug reports; keep ``previous`` for what they can't show."""
    previous = previous or Battery()
    readings = sorted((s for s in samples if _finite(s, "battery_pct")), key=lambda s: s["t"])
    changes = [b for a, b in pairwise(readings) if b["battery_pct"] != a["battery_pct"]]
    reports = sorted((r for r in plug if _finite(r, "w")), key=lambda r: r["t"])
    report_times = [r["t"] for r in reports]
    flows = Flows(samples, reports, previous)
    # Any output the Jackery reports means load is lowering the solar gain.
    drawing = sorted(s["t"] for s in samples if _finite(s, "output_w") and s["output_w"] > 0)
    ac_wh = ac_pct = solar_wh = solar_pct = 0.0
    for a, b in pairwise(changes):
        gain = b["battery_pct"] - a["battery_pct"]
        if gain <= 0 or not 0 < b["t"] - a["t"] <= MAX_SPAN:
            continue
        inside = reports[bisect_right(report_times, a["t"]) : bisect_right(report_times, b["t"])]
        bal = flows.between(a, b)
        if (
            inside
            and all(r["w"] >= MIN_CHARGE_W for r in inside)
            and bal.solar_read < 0.1 * bal.grid_wh
        ):
            ac_wh += bal.grid_wh
            ac_pct += gain
        elif (
            bal.grid_wh < 1
            and b["battery_pct"] < FULL_PCT
            and bal.solar_read / (b["t"] - a["t"]) * 3600 >= MIN_SOLAR_W
            and bisect_left(drawing, a["t"]) == bisect_right(drawing, b["t"])
        ):
            solar_wh += bal.solar_read
            solar_pct += gain
    capacity = previous.capacity_wh
    if ac_pct >= MIN_CAPACITY_PCT:
        capacity = _clamp(AC_CHARGE * ac_wh / ac_pct * 100, CAPACITY_RANGE)
    scale = previous.solar_scale
    if solar_pct >= MIN_SOLAR_PCT and solar_wh > 0:
        # Load the output reading misses lowers the gain, so this can only understate.
        scale = _clamp(capacity * solar_pct / 100 / SOLAR_CHARGE / solar_wh, SCALE_RANGE)
    return Battery(capacity_wh=capacity, solar_scale=scale)


def _draw(sample: dict) -> float | None:
    """Return charge over hours left, proportional to the battery's draw."""
    hours = sample.get("runtime_h")
    return sample["battery_pct"] / hours if hours else None


def _finite(s: dict, key: str) -> bool:
    return s.get(key) is not None and math.isfinite(s[key])


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])
