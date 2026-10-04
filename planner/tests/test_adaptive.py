from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from planner.adaptive import build_adaptive_plan, estimates
from planner.plan import PACIFIC
from planner.telemetry import CAPACITY_WH
from planner.watttime import drop_padding

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
    """Adam's 1:45 pm plan on 2026-10-04: 85% and one short window planned at
    1,700 W, but the battery charges at half that. Replanning every minute
    from live readings, as the server does, must still fill it by 4 pm. The
    only gaps are planned ones or a minute or two the plug bridges."""
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


def test_zero_padded_forecast_tail_is_never_scheduled():
    # WattTime pads the last hours of a forecast with 0. Planning at 5 pm, the
    # padding lands at 1:30-4 pm tomorrow, which must not read as the cleanest grid.
    now = datetime(2026, 10, 4, 17, tzinfo=PACIFIC)
    tail = now + timedelta(hours=20, minutes=30)
    points = [
        (t, 0.0 if t >= tail else 300 if t.astimezone(PACIFIC).hour == 11 else 900)
        for t in (now + timedelta(minutes=i * 5) for i in range(24 * 12))
    ]
    plan = build_adaptive_plan(points, now, 50, inputs(load=20, solar=0))
    assert plan["shortfall_wh"] == 0
    assert plan["windows"][0][0] == int(now.replace(day=5, hour=11).timestamp())
    assert all(e <= tail.timestamp() for _, e in plan["windows"])


def test_drop_padding_keeps_real_zeros():
    t = [NOW + timedelta(minutes=i * 5) for i in range(5)]
    points = list(zip(t, [400.0, 0.0, 300.0, 0.0, 0.0], strict=True))
    assert drop_padding(points) == points[:3]
    assert drop_padding([(t[0], 0.0)]) == []
