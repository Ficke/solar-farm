import pytest
from planner.battery import AC_CHARGE, SOLAR_CHARGE, Battery, measure

T0 = 1_791_150_000


def charging(capacity_wh: float, plug_w: float, minutes: int, start_pct: int = 50):
    """Readings and plug reports while only the plug charges the battery."""
    samples, plug = [], []
    for m in range(minutes + 1):
        t = T0 + m * 60
        stored = plug_w * AC_CHARGE * m / 60
        samples.append({"t": t, "battery_pct": start_pct + int(stored / capacity_wh * 100)})
        plug.append({"t": t, "w": plug_w})
    return samples, plug


def test_capacity_comes_from_the_plug_meter_while_charging():
    samples, plug = charging(2800, 1600, 30)
    assert measure(samples, plug).capacity_wh == pytest.approx(2800, rel=0.03)


def test_solar_scale_comes_from_sunny_spans_with_the_plug_off():
    # The sensor reads 60 W while the panel makes 90 W.
    samples = []
    for m in range(6 * 60 + 1):
        stored = 90 * SOLAR_CHARGE * m / 60
        samples.append(
            {"t": T0 + m * 60, "battery_pct": 40 + int(stored / 3000 * 100), "solar_w": 60.0}
        )
    battery = measure(samples, [], Battery(capacity_wh=3000))
    assert battery.solar_scale == pytest.approx(1.5, rel=0.05)
    assert battery.capacity_wh == 3000


def test_too_little_charging_keeps_the_previous_measurement():
    samples, plug = charging(2800, 1600, 4)
    previous = Battery(capacity_wh=2900, solar_scale=1.2)
    assert measure(samples, plug, previous) == previous
