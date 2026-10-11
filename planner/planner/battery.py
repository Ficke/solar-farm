"""Model the battery: its capacity, the solar reading's scale, and the energy balance.

Every estimate of energy into and out of the battery goes through ``Flows``:
the daily totals and CO2, the Power chart's load line, and the capacity and
solar-scale measurements.

The Jackery reports charge in whole percent and solar from its own sensor.
Its output reading lags and misses most draws, so the load is what came in
(solar, and grid from the plug's meter) less what the charge gained.

Between two readings where the charge changes, the battery gained exactly
that many percent. Over spans where only the plug charges it and the outlets
are off, the plug's meter times the charger efficiency gives Wh per percent,
which tracks capacity as the battery ages. Over sunny spans with the plug and
outlets off, that capacity times the gain, divided by the solar charge
efficiency, gives the panel's true output per Wh the sensor reports. Charger
and inverter efficiencies can't be separated from capacity without a meter on
the output, so they are assumed.
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
MIN_IDLE_H = 3  # Hours of quiet discharge before an idle measurement replaces the last.
MIN_REPORTS = 10  # Plug reports at full charge before a standby or bypass measurement does.
MAX_OVERHEAD_W = 100  # Above this, a plug report at full charge has a load on it.
STEADY = 1.25  # Largest ratio between runtime-based draws in a joined span.

type Rate = Callable[[float], float | None]  # Marginal CO2 in lb/MWh at a time.


def no_rate(_t: float) -> float | None:
    return None


@dataclass(frozen=True)
class Battery:
    capacity_wh: float = CAPACITY_WH  # usable Wh from 0 to 100%
    solar_scale: float = 1.0  # panel Wh per Wh of the Jackery's solar reading
    # The Jackery's own draw: outlets off, outlets on from the battery, and
    # outlets on while the plug passes power through.
    standby_w: float = 4.0
    idle_w: float = 45.0
    bypass_w: float = 31.0

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
    overhead: float = 0.0  # Wh of the load that is the Jackery's own draw
    short: float = 0.0  # Wh the charge gained beyond the measured input


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
        self.plug_times = [t for t, _ in series(plug, "w")]
        readings = sorted((s for s in samples if _finite(s, "battery_pct")), key=lambda s: s["t"])
        self.draw = [(s["t"], _draw(s)) for s in readings]
        self.draw_times = [t for t, _ in self.draw]
        self.fill = [(s["t"], _fill(s)) for s in readings]
        switched = sorted(
            (s["t"], s["outlets_on"]) for s in samples if s.get("outlets_on") is not None
        )
        self.switch_times = [t for t, _ in switched]
        self.switched = [on for _, on in switched]

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
        short = max(0.0, -load)
        overhead = self.overhead(t0, t1)
        if self.outlets_off(t0, t1):
            # Nothing to power but the Jackery itself; the rest is charging losses.
            load, direct, short = overhead, overhead * share, 0.0
        load = max(0.0, load)
        direct = min(max(0.0, direct), load)
        return Balance(
            load, direct, solar_read, solar_in, grid_wh, grid_lb, share, min(overhead, load), short
        )

    def overhead(self, t0: int, t1: int) -> float:
        """Return the Jackery's own Wh from its outlet state; 0 where that is unknown."""
        b = self.battery
        i = bisect_right(self.switch_times, t0) - 1
        j = bisect_right(self.switch_times, t1 - 1)
        cuts = [t0, *self.switch_times[i + 1 : j], t1]
        wh = 0.0
        for k, (t, u) in enumerate(pairwise(cuts), i):
            if k < 0:
                continue
            if not self.switched[k]:
                wh += b.standby_w * (u - t) / 3600
                continue
            plugged = self.supplied(u)[0] - self.supplied(t)[0]
            wh += b.bypass_w * plugged + b.idle_w * ((u - t) / 3600 - plugged)
        return wh

    def steady(self, t0: int, t1: int) -> bool:
        """Whether the plug stayed off and runtime estimates show a steady draw."""
        if self.supplied(t1)[0] != self.supplied(t0)[0] or self.timing(t0, t1) is None:
            return False
        i = bisect_right(self.draw_times, t0) - 1
        ws = [w for _, w in self.draw[i : bisect_right(self.draw_times, t1 - 1)] if w]
        return bool(ws) and max(ws) <= STEADY * min(ws)

    def outlets_off(self, t0: int, t1: int) -> bool:
        """Whether the Jackery reported its outlets switched off the whole time."""
        i = bisect_right(self.switch_times, t0) - 1
        j = bisect_right(self.switch_times, t1)
        return i >= 0 and not any(self.switched[i:j])

    def outlets_on(self, t0: int, t1: int) -> bool:
        """Whether the Jackery reported its outlets switched on the whole time."""
        i = bisect_right(self.switch_times, t0) - 1
        j = bisect_right(self.switch_times, t1)
        return i >= 0 and all(self.switched[i:j])

    def plugged(self, t0: int, t1: int) -> bool:
        """Whether the plug supplied power the whole time."""
        return self.supplied(t1)[0] - self.supplied(t0)[0] >= 0.99 * (t1 - t0) / 3600

    def timing(self, t0: int, t1: int) -> Callable[[float], float] | None:
        """Return the share of a span's load drawn by each time, or None without estimates."""
        return _shares(self.draw, self.draw_times, t0, t1)

    def metering(self, t0: int, t1: int) -> Callable[[float], float] | None:
        """Return the share of a span's grid energy drawn by each time, or None without any."""
        i, j = bisect_right(self.plug_times, t0), bisect_right(self.plug_times, t1 - 1)
        cuts = [t0, *self.plug_times[i:j], t1]
        start = self.grid(t0)[0]
        return _linear(cuts, [self.grid(t)[0] - start for t in cuts])

    def charging(self, a: dict, b: dict, bal: Balance) -> Callable[[float], float] | None:
        """Return the share of a charging span's load drawn by each time.

        Charge left over hours to full is proportional to the net charge rate,
        so it times the gain within the span. Between readings, the load is
        what came in less what was stored. None without estimates.
        """
        t0, t1 = a["t"], b["t"]
        stored = _shares(self.fill, self.draw_times, t0, t1)
        if stored is None or bal.load <= 0:
            return None
        gained = self.battery.wh(b["battery_pct"] - a["battery_pct"])
        out = bal.share * AC_CHARGE + (1 - bal.share) / DISCHARGE
        i, j = bisect_right(self.draw_times, t0), bisect_right(self.draw_times, t1 - 1)
        cuts = [t0, *self.draw_times[i:j], t1]
        sums = [0.0]
        for t, u in pairwise(cuts):
            came = (self.solar(u)[0] - self.solar(t)[0]) * self.battery.solar_stored + (
                self.grid(u)[0] - self.grid(t)[0]
            ) * AC_CHARGE
            sums.append(sums[-1] + max(0.0, (came - gained * (stored(u) - stored(t))) / out))
        return _linear(cuts, sums)


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
    done: Callable[[float], float]  # Share of the load beyond overhead drawn by a given time.
    overhead: float = 0.0  # Wh of the load that is the Jackery's own draw
    own: Callable[[float, float], float] = lambda _t, _u: 0.0  # Overhead Wh between two times.


def spans(
    samples: list[dict], plug: list[dict], battery: Battery, rate: Rate = no_rate
) -> list[Span]:
    """Split the load by whole-percent charge changes.

    Charge readings are whole percent (about 31 Wh), so the balance runs
    between readings where the charge changes. Within each span, the load
    follows the Jackery's runtime estimate: charge divided by hours left is
    proportional to the draw. While charging, its time to full times the gain
    instead. Spans mostly supplied from the plug follow the plug's meter. Other
    spans spread the load evenly.
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
    # half the real draw, and while the plug charges, between no load and a
    # spike. Join steps into spans of at least MIN_SPAN while the plug charges
    # throughout, or runtime estimates show a steady draw.
    edges = [steps[0]]
    for k, e in enumerate(steps[1:-1], 1):
        t0, t1 = edges[-1]["t"], steps[k + 1]["t"]
        if e["t"] - t0 >= MIN_SPAN or not (flows.plugged(t0, t1) or flows.steady(t0, t1)):
            edges.append(e)
    edges.append(steps[-1])
    out = []
    carry = 0.0
    for a, b in pairwise(edges):
        t0, t1 = a["t"], b["t"]
        if t1 <= t0:
            continue
        bal = flows.between(a, b)
        # Solar and timing noise make some spans gain more than came in. Take
        # that excess, up to 1%, from the next span's load instead of dropping
        # it, so the noise nets out. The first reading isn't a step: its
        # charge could be anywhere within the percent.
        take = min(carry, bal.load - bal.overhead)
        load = bal.load - take
        carry = min(bal.short, battery.wh(1)) if a is not steps[0] else 0.0
        done = flows.timing(t0, t1) if bal.share == 0 else None
        if done is None and b["battery_pct"] > a["battery_pct"]:
            done = flows.charging(a, b, bal)
        if done is None and bal.direct >= bal.load / 2 > 0:
            # Mostly passed through from the plug: follow its meter.
            done = flows.metering(t0, t1)
        out.append(
            Span(
                t0,
                t1,
                float(b["battery_pct"]),
                load,
                min(bal.direct, load),
                bal.solar_in,
                bal.grid_wh,
                bal.grid_lb,
                done or (lambda t, t0=t0, t1=t1: min(1.0, max(0.0, (t - t0) / (t1 - t0)))),
                bal.overhead,
                _scaled(
                    flows.overhead, bal.overhead / full if (full := flows.overhead(t0, t1)) else 0.0
                ),
            )
        )
    return out


def load_points(samples: list[dict], plug: list[dict], battery: Battery) -> list[tuple[int, float]]:
    """Return the estimated load in W from each sample to the next."""
    return [(t, round(w + o, 1)) for t, w, o in load_parts(samples, plug, battery)]


def load_parts(
    samples: list[dict], plug: list[dict], battery: Battery
) -> list[tuple[int, float, float]]:
    """Return the load beyond the Jackery's own draw and that draw, in W, per sample."""
    times = sorted(s["t"] for s in samples)
    points = []
    for span in spans(samples, plug, battery):
        inside = times[bisect_right(times, span.t0) : bisect_left(times, span.t1)]
        rest = span.load - span.overhead
        for t, u in pairwise([span.t0, *inside, span.t1]):
            points.append(
                (
                    t,
                    rest * (span.done(u) - span.done(t)) * 3600 / (u - t),
                    span.own(t, u) * 3600 / (u - t),
                )
            )
    return points


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

    def quiet(t0: int, t1: int, otherwise: bool) -> bool:
        """Whether nothing drew power: outlets off, or before outlet readings, ``otherwise``."""
        if bisect_right(flows.switch_times, t0):
            return flows.outlets_off(t0, t1)
        return otherwise

    ac_in = ac_pct = solar_wh = solar_pct = 0.0
    idle: list[tuple[float, float]] = []  # W and hours
    for a, b in pairwise(changes):
        gain = b["battery_pct"] - a["battery_pct"]
        if not 0 < b["t"] - a["t"] <= MAX_SPAN:
            continue
        bal = flows.between(a, b)
        if (
            gain < 0
            and bal.grid_wh < 1
            and bal.solar_read == 0
            and flows.outlets_on(a["t"], b["t"])
            and bisect_left(drawing, a["t"]) == bisect_right(drawing, b["t"])
        ):
            # Outlets on, nothing in and no output reading: usually the Jackery
            # idling, but the output reading misses some loads.
            hours = (b["t"] - a["t"]) / 3600
            idle.append((previous.wh(-gain) * DISCHARGE / hours, hours))
        if gain <= 0:
            continue
        inside = reports[bisect_right(report_times, a["t"]) : bisect_right(report_times, b["t"])]
        if (
            inside
            and all(r["w"] >= MIN_CHARGE_W for r in inside)
            and bal.solar_read < 0.1 * bal.grid_wh
            and quiet(a["t"], b["t"], True)
        ):
            # Count the little solar stored alongside, or no-load charging shows a load.
            ac_in += bal.grid_wh * AC_CHARGE + bal.solar_in
            ac_pct += gain
        elif (
            bal.grid_wh < 1
            and b["battery_pct"] < FULL_PCT
            and bal.solar_read / (b["t"] - a["t"]) * 3600 >= MIN_SOLAR_W
            and quiet(a["t"], b["t"], bisect_left(drawing, a["t"]) == bisect_right(drawing, b["t"]))
        ):
            solar_wh += bal.solar_read
            solar_pct += gain
    capacity = previous.capacity_wh
    if ac_pct >= MIN_CAPACITY_PCT:
        capacity = _clamp(ac_in / ac_pct * 100, CAPACITY_RANGE)
    scale = previous.solar_scale
    if solar_pct >= MIN_SOLAR_PCT and solar_wh > 0:
        # Load the output reading misses lowers the gain, so this can only understate.
        scale = _clamp(capacity * solar_pct / 100 / SOLAR_CHARGE / solar_wh, SCALE_RANGE)
    idle_w = previous.idle_w
    if sum(h for _, h in idle) >= MIN_IDLE_H:
        idle_w = _clamp(_median(idle), (0, MAX_OVERHEAD_W))
    standby, bypass = _full_draws(readings, reports, flows)
    return Battery(
        capacity_wh=capacity,
        solar_scale=scale,
        standby_w=_median([(w, 1) for w in standby])
        if len(standby) >= MIN_REPORTS
        else previous.standby_w,
        idle_w=idle_w,
        bypass_w=_median([(w, 1) for w in bypass])
        if len(bypass) >= MIN_REPORTS
        else previous.bypass_w,
    )


def _full_draws(
    samples: list[dict], reports: list[dict], flows: Flows
) -> tuple[list[float], list[float]]:
    """Return the plug's draw at full charge with nothing running, outlets off and on.

    Full and without sun or output, the Jackery passes the plug's power only to
    itself.
    """
    times = [s["t"] for s in samples]
    off, on = [], []
    for r in reports:
        i = bisect_right(times, r["t"]) - 1
        if i < 0 or not 0 < r["w"] < MAX_OVERHEAD_W:
            continue
        s = samples[i]
        if s.get("battery_pct") != 100 or s.get("solar_w") or s.get("output_w"):
            continue
        k = bisect_right(flows.switch_times, r["t"]) - 1
        if k >= 0:
            (on if flows.switched[k] else off).append(r["w"])
    return off, on


def _median(weighted: list[tuple[float, float]]) -> float:
    """Return the weighted median of (value, weight) pairs."""
    points = sorted(weighted)
    half = sum(w for _, w in points) / 2
    seen = 0.0
    for value, w in points:
        seen += w
        if seen >= half:
            return value
    return points[-1][0]


def _scaled(f: Callable[[int, int], float], k: float) -> Callable[[float, float], float]:
    return lambda t, u: f(int(t), int(u)) * k


def _draw(sample: dict) -> float | None:
    """Return charge over hours left, proportional to the battery's draw."""
    hours = sample.get("runtime_h")
    return sample["battery_pct"] / hours if hours else None


def _fill(sample: dict) -> float | None:
    """Return charge left over hours to full, proportional to the net charge rate."""
    hours = sample.get("full_h")
    return (100 - sample["battery_pct"]) / hours if hours else None


def _shares(
    weights: list[tuple[int, float | None]], times: list[int], t0: int, t1: int
) -> Callable[[float], float] | None:
    """Return the share of a span done by each time; each weight holds until the next reading."""
    i = bisect_right(times, t0) - 1
    j = bisect_right(times, t1 - 1)
    steps = weights[max(i, 0) : j]
    if i < 0 or any(w is None for _, w in steps):
        return None
    cuts = [t0] + [t for t, _ in steps[1:]] + [t1]
    sums = [0.0]
    for (t, u), (_, w) in zip(pairwise(cuts), steps, strict=True):
        sums.append(sums[-1] + (w or 0.0) * (u - t))
    return _linear(cuts, sums)


def _linear(cuts: list[int], sums: list[float]) -> Callable[[float], float] | None:
    """Return the cumulative share at a time, interpolating between cuts; None if all zero."""
    total = sums[-1]
    if total <= 0:
        return None

    def done(t: float) -> float:
        if t <= cuts[0]:
            return 0.0
        if t >= cuts[-1]:
            return 1.0
        k = bisect_right(cuts, t) - 1
        f = (t - cuts[k]) / (cuts[k + 1] - cuts[k])
        return (sums[k] + (sums[k + 1] - sums[k]) * f) / total

    return done


def _finite(s: dict, key: str) -> bool:
    return s.get(key) is not None and math.isfinite(s[key])


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])
