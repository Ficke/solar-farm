from datetime import UTC, datetime, timedelta

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


def test_small_topup_uses_clean_hour_and_leaves_solar_room():
    plan = build_adaptive_plan(forecast(), NOW, 60, inputs(load=20))
    assert plan["target_pct"] == pytest.approx(83.7)
    assert plan["shortfall_wh"] == 0
    assert plan["grid_wh"] < 150
    assert plan["windows"]
    for s, e in plan["windows"]:
        assert datetime.fromtimestamp(s, PACIFIC).hour == 12
        assert e - s < 15 * 60


def test_charging_follows_emissions_forecast_when_cleanest_window_moves():
    estimate = inputs(load=20)
    for clean_hour in (11, 14):
        plan = build_adaptive_plan(forecast(clean=clean_hour), NOW, 60, estimate)
        assert plan["windows"]
        assert all(
            datetime.fromtimestamp(s, PACIFIC).hour == clean_hour for s, _ in plan["windows"]
        )


def test_solar_can_cover_the_load_without_any_grid():
    plan = build_adaptive_plan(forecast(), NOW, 85, inputs(load=10))
    assert plan["windows"] == []
    assert plan["grid_wh"] == 0


def test_low_battery_does_not_trigger_a_needless_fill_when_solar_covers_load():
    plan = build_adaptive_plan(forecast(), NOW, 25, inputs(load=10))
    assert plan["windows"] == []


def test_low_battery_cannot_wait_for_cleanest_hour():
    plan = build_adaptive_plan(forecast(clean=14), NOW, 22, inputs(load=100, solar=0))
    assert plan["shortfall_wh"] == 0
    assert plan["windows"][0][0] < int((NOW + timedelta(hours=1)).timestamp())


def test_faster_charging_needs_less_grid_time():
    slow = build_adaptive_plan(forecast(), NOW, 60, inputs(charge=600))
    fast = build_adaptive_plan(forecast(), NOW, 60, inputs(charge=1200))

    def duration(p):
        return sum(e - s for s, e in p["windows"])

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


def test_larger_solar_days_lower_grid_target():
    plan = build_adaptive_plan(forecast(), NOW, 80, inputs(solar=1000))
    assert plan["target_pct"] == pytest.approx(round((1 - 1000 / CAPACITY_WH) * 100, 1))


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
    assert plan["target_pct"] > sunnier["target_pct"]


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
