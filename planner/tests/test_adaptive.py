from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from planner.adaptive import build_adaptive_plan, estimates
from planner.plan import PACIFIC
from planner.telemetry import CAPACITY_WH

NOW = datetime(2026, 10, 3, 14, tzinfo=UTC)  # 7am Pacific


def inputs(load=30, solar=500, charge=1700):
    return estimates([], int(NOW.timestamp()), solar, load, charge)


def forecast(hours=24, clean=12):
    return [
        (
            NOW + timedelta(minutes=i * 5),
            10 if (NOW + timedelta(minutes=i * 5)).astimezone(PACIFIC).hour == clean else 900,
        )
        for i in range(hours * 12)
    ]


def duration(p):
    return sum(e - s for s, e in p["windows"])


def test_fills_to_full_in_the_clean_hour():
    plan = build_adaptive_plan(forecast(), NOW, 60, inputs(load=20))
    assert plan["target_pct"] == 100
    assert plan["shortfall_wh"] == 0
    assert 1000 < plan["grid_wh"] < 1400  # 40% of the battery, less morning solar
    assert plan["windows"]
    for s, e in plan["windows"]:
        assert datetime.fromtimestamp(s, PACIFIC).hour == 12
        assert datetime.fromtimestamp(e - 1, PACIFIC).hour == 12


def test_charging_follows_emissions_forecast_when_cleanest_window_moves():
    estimate = inputs(load=20)
    for clean_hour in (11, 14):
        plan = build_adaptive_plan(forecast(clean=clean_hour), NOW, 60, estimate)
        assert plan["windows"]
        assert all(
            datetime.fromtimestamp(s, PACIFIC).hour == clean_hour for s, _ in plan["windows"]
        )


def test_full_battery_needs_no_grid():
    plan = build_adaptive_plan(forecast(), NOW, 100, inputs(load=10))
    assert plan["windows"] == []
    assert plan["grid_wh"] == 0


def test_low_battery_cannot_wait_for_cleanest_hour():
    plan = build_adaptive_plan(forecast(clean=14), NOW, 22, inputs(load=100, solar=0))
    assert plan["shortfall_wh"] == 0
    assert plan["windows"][0][0] < int((NOW + timedelta(hours=1)).timestamp())


def test_faster_charging_needs_less_grid_time():
    slow = build_adaptive_plan(forecast(), NOW, 60, inputs(charge=600))
    fast = build_adaptive_plan(forecast(), NOW, 60, inputs(charge=1200))

    assert duration(fast) < duration(slow)
    assert fast["grid_wh"] == pytest.approx(slow["grid_wh"], abs=30)


def test_peak_is_excluded_even_if_cleanest_and_infeasible_plan_is_reported():
    plan = build_adaptive_plan(forecast(clean=18), NOW, 20, inputs(load=500, charge=100))
    assert plan["shortfall_wh"] > 0
    for s, e in plan["windows"]:
        assert s >= int(NOW.timestamp())
        assert not 16 <= datetime.fromtimestamp(s, PACIFIC).hour < 21
        assert not 16 <= datetime.fromtimestamp(e - 1, PACIFIC).hour < 21


def test_current_block_is_clipped_to_now():
    now = NOW + timedelta(minutes=7)
    plan = build_adaptive_plan(forecast(), now, 20, inputs(load=100))
    assert all(s >= int(now.timestamp()) for s, _ in plan["windows"])


def test_history_learns_solar_and_load_without_extrapolating_gaps():
    start = int((NOW - timedelta(days=1, hours=7)).timestamp())  # yesterday midnight
    samples = []
    for i in range(288):
        t = start + i * 300
        hour = datetime.fromtimestamp(t, PACIFIC).hour
        samples.append(
            {
                "t": t,
                "solar_w": 100 if 10 <= hour < 15 else 0,
                "output_w": 40,
                "ac_input_w": 1200 if hour == 8 else 0,
                "battery_pct": 50,
            }
        )
    estimate = estimates(samples, int(NOW.timestamp()), 500, 100, 1700)
    assert estimate["solar_days"] == 1
    assert estimate["solar_day_wh"] == pytest.approx(500)
    # Charge held at 50% with 500 Wh of solar and 1.2 kWh of grid in over the
    # last 24 hours of readings (7 am to midnight): the load drew it all.
    hours = (samples[-1]["t"] - int((NOW - timedelta(days=1)).timestamp())) / 3600
    assert estimate["load_w"] == pytest.approx((500 + 1200) * 0.9 * 0.9 / hours, rel=0.01)
    assert estimate["charge_w"] == pytest.approx(1160)  # AC in less load, as measured
    assert estimate["solar_profile"][48] == pytest.approx(100)
    sparse = estimates([samples[0], samples[-1]], int(NOW.timestamp()), 500, 100, 1700)
    assert sparse["solar_days"] == 0
    assert sparse["load_w"] == 100


def test_equal_forecasts_charge_as_late_as_possible():
    flat = [(NOW + timedelta(minutes=i * 5), 900.0 + i % 3) for i in range(24 * 12)]
    plan = build_adaptive_plan(flat, NOW, 80, inputs(load=20))
    assert plan["windows"][-1][1] <= plan["deadline"]
    assert datetime.fromtimestamp(plan["windows"][-1][0], PACIFIC).hour == 15
    assert datetime.fromtimestamp(plan["deadline"], PACIFIC).hour == 16


def test_room_is_kept_only_for_material_later_solar():
    early = forecast(clean=10)
    none = build_adaptive_plan(early, NOW, 60, inputs(load=5, solar=0))
    small = build_adaptive_plan(early, NOW, 60, inputs(load=5, solar=200))
    big = build_adaptive_plan(early, NOW, 60, inputs(load=5, solar=2000))
    # 200 Wh/day leaves too little after 10am to wait for: fill up at 10.
    assert none["grid_wh"] - small["grid_wh"] < 100
    # 2,000 Wh/day: keep room for half of what usually comes after 10.
    assert none["grid_wh"] - big["grid_wh"] > 600
    assert big["shortfall_wh"] == 0


def test_after_peak_the_plan_aims_for_tomorrow_afternoon():
    evening = datetime(2026, 10, 4, 4, 30, tzinfo=UTC)  # 9:30pm Pacific
    points = [
        (evening + timedelta(minutes=i * 5), 900.0 if i < 12 * 14 else 100.0)
        for i in range(48 * 12)
    ]
    plan = build_adaptive_plan(points, evening, 40, inputs(load=20))
    assert datetime.fromtimestamp(plan["deadline"], PACIFIC).day == 4
    assert plan["windows"]
    assert all(s >= int((evening + timedelta(hours=14)).timestamp()) for s, _ in plan["windows"])
    assert plan["shortfall_wh"] == 0


def test_solar_estimate_follows_recent_days_and_ignores_older_history():
    samples = []
    midnight = NOW - timedelta(hours=7)
    for days_ago in range(1, 15):
        start = int((midnight - timedelta(days=days_ago)).timestamp())
        for i in range(288):
            t = start + i * 300
            hour = datetime.fromtimestamp(t, PACIFIC).hour
            watts = 50 if days_ago <= 7 else 200
            samples.append({"t": t, "solar_w": watts if 10 <= hour < 15 else 0})
    estimate = estimates(samples, int(NOW.timestamp()), 500, 100, 1700)
    assert estimate["solar_days"] == 7
    assert estimate["solar_day_wh"] == pytest.approx(250)
    assert estimate["solar_profile"][48] == pytest.approx(50)
    plan = build_adaptive_plan(forecast(), NOW, 60, estimate)
    sunnier = build_adaptive_plan(forecast(), NOW, 60, inputs(load=100, solar=750))
    assert plan["grid_wh"] > sunnier["grid_wh"]


def test_a_day_with_missing_midday_data_is_not_treated_as_low_solar():
    start = int((NOW - timedelta(days=1, hours=7)).timestamp())
    samples = [
        {"t": start + i * 300, "solar_w": 100}
        for i in range(288)
        if not 11 <= datetime.fromtimestamp(start + i * 300, PACIFIC).hour < 14
    ]
    estimate = estimates(samples, int(NOW.timestamp()), 500, 100, 1700)
    assert estimate["solar_days"] == 0
    assert estimate["solar_day_wh"] == 500


def test_invalid_and_duplicate_samples_do_not_distort_estimates():
    start = int((NOW - timedelta(days=1, hours=7)).timestamp())
    samples: list[dict] = [{"t": start + i * 300, "solar_w": 0, "output_w": 40} for i in range(288)]
    samples.extend(
        [samples[0], {"t": start + 300, "solar_w": float("nan"), "output_w": float("inf")}]
    )
    estimate = estimates(list(reversed(samples)), int(NOW.timestamp()), 500, 100, 1700)
    assert estimate["solar_day_wh"] == 0
    assert estimate["load_w"] == pytest.approx(40)


def test_load_comes_from_the_energy_balance_not_the_output_reading():
    # Ten hours of the battery falling 10% with no solar or grid, while the
    # Jackery's output reading shows almost nothing (it lags and undercounts).
    t = int(NOW.timestamp())
    samples = [
        {"t": t - 36000 + i * 60, "battery_pct": 90 - i // 60, "solar_w": 0, "output_w": 0}
        for i in range(601)
    ]
    load = estimates(samples, t, 500, 5, 1700)["load_w"]
    assert load == pytest.approx(CAPACITY_WH * 0.10 * 0.9 / 10, rel=0.01)  # about 28 W


def test_plug_meter_supplies_grid_energy_and_charge_rate():
    # Six hours: 1 kWh in on the plug's meter while the Jackery's AC reading
    # shows nothing; the charge rose 25%, so the load drew the rest.
    t = int(NOW.timestamp())
    start = t - 6 * 3600
    samples = [
        {"t": start + i * 60, "battery_pct": 60 + 25 * i / 360, "solar_w": 0, "ac_input_w": 0}
        for i in range(361)
    ]
    plug = [
        {
            "t": start + i * 60,
            "on": i < 36,
            "w": 1660.0 if i < 36 else 0.0,
            "wh": min(i, 36) / 36 * 1000,
        }
        for i in range(361)
    ]
    plug.append({"t": t + 600, "on": True, "w": 9999.0, "wh": 0.0})  # after now: ignored
    estimate = estimates(samples, t, 500, 5, 1200, plug=plug)
    expected = (1000 * 0.9 - CAPACITY_WH * 0.25) * 0.9 / 6
    assert estimate["load_w"] == pytest.approx(expected, rel=0.01)
    assert estimate["charge_w"] == pytest.approx(1660)
    # Near full the Jackery slows down; those readings don't set the rate.
    full = [dict(s, battery_pct=97) for s in samples]
    assert estimates(full, t, 500, 5, 1200, plug=plug)["charge_w"] == 1200


def test_charge_rate_ignores_passthrough_and_needs_a_few_readings():
    t = int(NOW.timestamp())
    few = [{"t": t - 600, "ac_input_w": 1500.0, "output_w": 0.0}]
    assert estimates(few, t, 500, 100, 1700)["charge_w"] == 1700
    readings = [
        {"t": t - 300 * i, "ac_input_w": w, "output_w": 50.0}
        for i, w in enumerate([1050.0, 1050.0, 1100.0, 150.0, 220.0, float("nan")])
    ]
    assert estimates(readings, t, 500, 100, 1700)["charge_w"] == pytest.approx(1000)


def adams_forecast(day: datetime) -> list[tuple[datetime, float]]:
    """2026-10-04: near zero from noon to 2pm, about 535 until the 4pm peak."""
    out = []
    for i in range(30 * 12):
        t = day + timedelta(minutes=i * 5)
        hour = t.astimezone(PACIFIC).hour
        out.append((t, 2.0 if 12 <= hour < 14 else 535.0 if 14 <= hour < 16 else 950.0))
    return out


def test_current_block_stays_planned_between_forecast_points():
    points = adams_forecast(datetime(2026, 10, 4, 18, tzinfo=UTC))  # 11am Pacific
    now = datetime(2026, 10, 4, 13, 58, tzinfo=PACIFIC)
    plan = build_adaptive_plan(points, now, 93, inputs(load=1))
    assert plan["windows"][0][0] == int(now.timestamp())


def test_slow_charging_still_fills_by_4pm():
    """Verify minute replans reach full by 4 pm when charging at half the estimate."""
    points = adams_forecast(datetime(2026, 10, 4, 18, tzinfo=UTC))
    now = datetime(2026, 10, 4, 13, 45, tzinfo=PACIFIC)
    first = build_adaptive_plan(points, now, 85, inputs(load=1))
    assert first["windows"][0][0] == int(now.timestamp())
    assert first["windows"][0][1] - first["windows"][0][0] <= 20 * 60
    pct, samples, on_minutes = 85.0, [], []
    estimate = inputs(load=1)
    while now.astimezone(PACIFIC).hour < 16:
        t = int(now.timestamp())
        if now.minute % 5 == 0:  # the server's estimate refresh while charging
            estimate = estimates(samples, t, 500, 1, 1700)
        plan = build_adaptive_plan(points, now, pct, estimate)
        on = any(s <= t < e for s, e in plan["windows"])
        if on:
            on_minutes.append(t)
            pct = min(100.0, pct + 850 * 0.9 / 60 / CAPACITY_WH * 100)
        samples.append({"t": t, "ac_input_w": 850.0 if on else 0.0, "output_w": 1.0})
        now += timedelta(minutes=1)
    assert pct >= 99
    gaps = [b - a - 60 for a, b in pairwise(on_minutes) if b - a > 60]
    assert all(g <= 180 or g >= 15 * 60 for g in gaps), gaps


def test_blocks_without_forecast_are_never_scheduled():
    # Missing forecast points mean unknown, not 0 lb/MWh: the clean hour is
    # used, the gap before it is not, even though the rest of the day is dirty.
    gap = range(4 * 12, 5 * 12)  # 11 am-noon Pacific
    points = [p for i, p in enumerate(forecast(clean=12)) if i not in gap]
    plan = build_adaptive_plan(points, NOW, 40, inputs(load=20, solar=0))
    assert plan["windows"]
    for s, _ in plan["windows"]:
        assert datetime.fromtimestamp(s, PACIFIC).hour != 11


def flat(rate, now=NOW, hours=24, cleaner=None):
    """A forecast at ``rate``, with ``cleaner`` = {Pacific hour: rate} overrides."""
    out = []
    for i in range(hours * 12):
        t = now + timedelta(minutes=i * 5)
        out.append((t, (cleaner or {}).get(t.astimezone(PACIFIC).hour, rate)))
    return out


def test_full_battery_runs_the_load_from_the_grid_when_that_beats_recharging():
    # Sunday-like: 1,000 lb/MWh all day, 900 from 1 to 2 pm. Draining the full
    # battery now means recharging at 900 / 0.81 = 1,111 later, so the load
    # runs from the grid instead and the battery stays full.
    plan = build_adaptive_plan(flat(1000, cleaner={13: 900}), NOW, 100, inputs(load=200, solar=0))
    assert plan["windows"] == [[int(NOW.timestamp()), plan["deadline"]]]
    assert plan["bypass_wh"] == pytest.approx(200 * 9, rel=0.01)
    assert plan["shortfall_wh"] == 0


def test_battery_runs_the_load_when_a_curtailment_block_will_refill_it():
    # Grid at 0 from noon to 2 pm: run the load from the battery this morning
    # and recharge in the clean block rather than buying 900 now. After 2 pm
    # nothing cleaner is left, so the grid runs the load until 4 pm.
    plan = build_adaptive_plan(
        flat(900, cleaner={12: 0, 13: 0}), NOW, 100, inputs(load=200, solar=0)
    )
    two = int(NOW.replace(hour=21).timestamp())  # 2 pm Pacific
    assert plan["windows"][0][0] >= int(NOW.replace(hour=19).timestamp())  # not before noon
    assert plan["windows"][-1][1] == plan["deadline"]
    assert plan["bypass_wh"] == pytest.approx(200 * (plan["deadline"] - two) / 3600, rel=0.01)
    assert plan["shortfall_wh"] == 0


def test_no_bypass_while_room_is_kept_for_solar():
    # Morning with solar still to come: keeping the battery full from the grid
    # would leave the panels nowhere to go.
    plan = build_adaptive_plan(flat(1000), NOW, 100, inputs(load=200, solar=2000))
    assert all(datetime.fromtimestamp(s, PACIFIC).hour >= 9 for s, _ in plan["windows"])


def test_held_window_keeps_its_place_unless_clearly_beaten():
    # 10 am at 480 and 11 am at 500 tie; the later block wins by default.
    points = flat(900, cleaner={10: 480, 11: 500})
    estimate = inputs(load=20, solar=0)
    first = build_adaptive_plan(points, NOW, 85, estimate)
    assert datetime.fromtimestamp(first["windows"][0][0], PACIFIC).hour == 11
    # A plan already holding 10 am keeps it within the tie band ...
    ten = int(NOW.replace(hour=17).timestamp())  # 10 am Pacific
    held = build_adaptive_plan(points, NOW, 85, estimate, hold=[[ten, ten + 900]])
    assert datetime.fromtimestamp(held["windows"][0][0], PACIFIC).hour == 10
    # ... but gives way to a block more than 50 lb/MWh cleaner.
    cleaner = flat(900, cleaner={10: 480, 11: 420})
    moved = build_adaptive_plan(cleaner, NOW, 85, estimate, hold=[[ten, ten + 900]])
    assert datetime.fromtimestamp(moved["windows"][0][0], PACIFIC).hour == 11


def test_solar_is_learned_only_while_the_battery_has_room():
    start = int((NOW - timedelta(days=1, hours=7)).timestamp())  # yesterday midnight
    samples = []
    for i in range(288):
        t = start + i * 300
        hour = datetime.fromtimestamp(t, PACIFIC).hour
        full = hour >= 12  # full from noon: solar input cut to 20 W
        samples.append(
            {
                "t": t,
                "solar_w": (20 if full else 200) if 9 <= hour < 15 else 0,
                "battery_pct": 100 if full else 80,
            }
        )
    estimate = estimates(samples, int(NOW.timestamp()), 500, 10, 1700)
    assert estimate["solar_days"] == 1
    assert estimate["solar_profile"][40] == pytest.approx(200)  # 10 am, with room
    # Noon to 5 pm was never seen with room, so it keeps the configured estimate.
    assert estimate["solar_profile"][52] == pytest.approx(500 / 8)
    assert estimate["solar_day_wh"] == pytest.approx(3 * 200 + 5 * 500 / 8, rel=0.02)
