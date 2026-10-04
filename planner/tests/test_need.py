from datetime import datetime, timedelta

from planner.need import grid_need, next_deadline
from planner.plan import PACIFIC

# Sat 3 Oct 2026, 08:00 Pacific: 8 hours to the peak
NOW = datetime(2026, 10, 3, 8, 0, tzinfo=PACIFIC)


def week(battery_pct=50.0, solar=None, load=0.0, ac_in=0.0):
    """5-minute samples for the past week; solar watts by local hour."""
    solar = solar or {}
    out = []
    t = NOW - timedelta(days=7)
    while t <= NOW:
        out.append(
            {
                "t": int(t.timestamp()),
                "battery_pct": battery_pct,
                "solar_w": solar.get(t.hour, 0.0),
                "ac_input_w": ac_in,
                "output_w": load,
            }
        )
        t += timedelta(minutes=5)
    return out


def test_deadline_is_the_next_peak_start():
    assert next_deadline(NOW) == datetime(2026, 10, 3, 16, 0, tzinfo=PACIFIC)
    evening = NOW.replace(hour=16)
    assert next_deadline(evening) == datetime(2026, 10, 4, 16, 0, tzinfo=PACIFIC)


def test_grid_covers_only_what_solar_leaves_short():
    # 50% now, 80% reserve: 921.6 Wh short. 200 W from 10:00 to 14:00 is 800 Wh.
    need = grid_need(week(solar={10: 200, 11: 200, 12: 200, 13: 200}), NOW)
    assert need is not None
    assert need["solar_wh"] == 800 and need["load_wh"] == 0
    assert need["grid_wh"] == 122
    # No charging seen yet, so 1,000 W: one half-hour plus the spare.
    assert need["rate_w"] == 1000 and need["blocks"] == 2


def test_load_before_the_peak_adds_to_the_need():
    need = grid_need(week(load=100.0), NOW)
    assert need is not None
    assert need["load_wh"] == 800 and need["grid_wh"] == 1722


def test_nothing_from_the_grid_when_solar_covers_it():
    need = grid_need(week(battery_pct=70.0, solar={11: 400, 12: 400}), NOW)
    assert need is not None
    assert need["grid_wh"] == 0 and need["blocks"] == 0


def test_charge_rate_is_measured():
    samples = week(load=100.0, ac_in=100.0)  # passthrough only
    for s in samples[-6:]:
        s["ac_input_w"] = 1500.0
    need = grid_need(samples, NOW)
    assert need is not None
    assert need["rate_w"] == 1400
    assert need["blocks"] == 3 + 1  # 1,722 Wh at 700 Wh a half-hour, plus the spare


def test_no_recent_battery_reading_means_no_estimate():
    old = [s for s in week() if s["t"] < NOW.timestamp() - 3600]
    assert grid_need(old, NOW) is None
    assert grid_need([], NOW) is None
