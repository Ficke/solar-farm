from datetime import datetime, timedelta, timezone

from planner.plan import PACIFIC, build_plan
from planner.watttime import parse_forecast, parse_signal_index


def forecast_from(start: datetime, values_by_hour: dict[int, float], hours: int = 24):
    """5-minute points; MOER by local hour, default 900 (dirty)."""
    points = []
    for i in range(hours * 12):
        t = start + timedelta(minutes=5 * i)
        points.append((t, values_by_hour.get(t.astimezone(PACIFIC).hour, 900.0)))
    return points


# 2026-10-03 07:00 PDT
NOW = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)


def local_hours(plan):
    hours = set()
    for s, e in plan["windows"]:
        t = s
        while t < e:
            hours.add(datetime.fromtimestamp(t, PACIFIC).hour)
            t += 1800
    return hours


def test_picks_cleanest_hours_and_merges_them():
    pts = forecast_from(NOW, {11: 50, 12: 40, 13: 60, 14: 300})
    plan = build_plan(pts, NOW, budget_hours=3)
    assert local_hours(plan) == {11, 12, 13}
    assert len(plan["windows"]) == 1
    s, e = plan["windows"][0]
    assert e - s == 3 * 3600
    assert plan["generated_at"] == int(NOW.timestamp())


def test_never_schedules_peak_even_if_cleanest():
    pts = forecast_from(NOW, {16: 1, 17: 1, 18: 1, 20: 1, 12: 100, 13: 100})
    plan = build_plan(pts, NOW, budget_hours=2)
    assert local_hours(plan) == {12, 13}


def test_skips_blocks_already_past():
    pts = forecast_from(NOW - timedelta(hours=2), {5: 1, 6: 1, 12: 100})
    plan = build_plan(pts, NOW, budget_hours=1)
    assert local_hours(plan) == {12}


def test_parse_forecast():
    body = {"data": [{"point_time": "2026-10-03T17:30:00+00:00", "value": 812.5}]}
    [(t, v)] = parse_forecast(body)
    assert t == datetime(2026, 10, 3, 17, 30, tzinfo=timezone.utc)
    assert v == 812.5


def test_parse_signal_index():
    body = {"data": [{"point_time": "2026-10-03T17:35:00+00:00", "value": 37.0}], "meta": {}}
    assert parse_signal_index(body) == 37.0
