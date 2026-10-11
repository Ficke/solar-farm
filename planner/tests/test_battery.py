import pytest
from planner.battery import AC_CHARGE, DISCHARGE, SOLAR_CHARGE, Battery, load_parts, measure

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


def test_capacity_skips_charging_while_the_outlets_are_on():
    samples, plug = charging(2800, 1600, 30)
    on = [dict(s, outlets_on=True) for s in samples]
    assert measure(on, plug, Battery(capacity_wh=3000)).capacity_wh == 3000
    off = [dict(s, outlets_on=False) for s in samples]
    assert measure(off, plug).capacity_wh == pytest.approx(2800, rel=0.03)


def test_too_little_charging_keeps_the_previous_measurement():
    samples, plug = charging(2800, 1600, 4)
    previous = Battery(capacity_wh=2900, solar_scale=1.2)
    assert measure(samples, plug, previous) == previous


def test_solar_spans_with_reported_output_are_skipped():
    # A 40 W load for three hours hides part of the panel's output; the output
    # reading flags it, so only the last five hours count.
    samples = []
    for m in range(8 * 60 + 1):
        load = m < 3 * 60
        stored = 90 * SOLAR_CHARGE * m / 60 - (40 * min(m, 180) / 60)
        samples.append(
            {
                "t": T0 + m * 60,
                "battery_pct": 40 + int(stored / 3000 * 100),
                "solar_w": 60.0,
                "output_w": 40.0 if load else 0.0,
            }
        )
    battery = measure(samples, [], Battery(capacity_wh=3000))
    assert battery.solar_scale == pytest.approx(1.5, rel=0.1)


def test_idle_draw_comes_from_quiet_discharge_with_the_outlets_on():
    # The outlets are on, nothing comes in, and 1% goes every 40 minutes.
    battery = Battery(capacity_wh=3000)
    samples = [
        {"t": T0 + m * 60, "battery_pct": 80 - m // 40, "outlets_on": True, "output_w": 0.0}
        for m in range(6 * 60 + 1)
    ]
    measured = measure(samples, [], battery)
    assert measured.idle_w == pytest.approx(30 * DISCHARGE * 60 / 40, rel=0.01)


def test_standby_and_pass_through_draws_come_from_the_plug_at_full_charge():
    samples, plug = [], []
    for m in range(80):
        on = m >= 40
        samples.append({"t": T0 + m * 60, "battery_pct": 100.0, "outlets_on": on})
        plug.append({"t": T0 + m * 60 + 10, "w": 31.0 if on else 3.7})
    measured = measure(samples, plug)
    assert (measured.standby_w, measured.bypass_w) == (3.7, 31.0)


def test_load_splits_the_jackery_draw_from_appliances():
    battery = Battery(capacity_wh=3000, idle_w=45.0)
    # The battery drains 45 W more than the Jackery's idle draw.
    per_pct = 30 * DISCHARGE / 90 * 60  # minutes per percent at 90 W
    samples = [
        {"t": T0 + m * 60, "battery_pct": 80 - int(m / per_pct), "outlets_on": True}
        for m in range(241)
    ]
    parts = load_parts(samples, [], battery)
    middle = parts[len(parts) // 2]
    assert middle[1] == pytest.approx(45, rel=0.05)
    assert middle[2] == pytest.approx(45, rel=0.01)
