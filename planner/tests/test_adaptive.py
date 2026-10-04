from datetime import UTC, datetime, timedelta

import pytest
from planner.adaptive import build_adaptive_plan, estimates
from planner.plan import PACIFIC

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
    assert estimate["load_w"] == pytest.approx(40)
    assert estimate["charge_w"] == 1700  # observed AC input doesn't override the assumption
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
