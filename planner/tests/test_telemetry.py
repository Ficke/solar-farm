from datetime import UTC, datetime, timedelta

from planner.jackery import parse_properties, scalars, stat_summary

from planner import telemetry

START = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)  # midnight PDT


def day_of_samples(day_offset: int, peak_w: float):
    """48 half-hour samples; a triangle of solar from 9am to 5pm local."""
    out = []
    for i in range(48):
        t = START + timedelta(days=day_offset, minutes=30 * i)
        hour = i / 2
        w = max(0.0, peak_w * (1 - abs(hour - 13) / 4))
        out.append((t, w))
    return out


def test_parse_properties_derives_solar():
    r = parse_properties({"properties": {"rb": 72, "ip": 260, "acip": 40, "op": 55}}, START)
    assert r.battery_pct == 72
    assert r.solar_w == 220


def test_scalars_drops_nested_values():
    props = {"properties": {"rb": 72, "acps": 0, "name": "E3000", "packs": [1], "x": {}}}
    assert scalars(props) == {"rb": 72, "acps": 0, "name": "E3000"}


def test_stat_summary_reports_codes_and_errors():
    responses = {
        "/a": {"status": 200, "body": '{"code":0,"msg":"ok"}'},
        "/b": {"status": 502, "body": "<html>"},
        "/c": {"error": "TimeoutError()"},
    }
    assert stat_summary(responses) == {"/a": "0 ok", "/b": "502", "/c": "TimeoutError()"}


def test_daily_solar_and_recommendation():
    samples = []
    for d in range(10):
        samples += day_of_samples(d, peak_w=150)  # ~600 Wh/day
    daily = telemetry.daily_solar_wh(samples)
    assert len(daily) == 10
    assert all(abs(wh - 600) < 20 for wh in daily.values())
    rec = telemetry.recommend_reserve(daily)
    assert rec["reserve_pct"] == 80
    assert rec["days"] == 10


def test_partial_days_are_ignored_and_reserve_is_clamped():
    samples = day_of_samples(0, 150)[:20]
    assert telemetry.daily_solar_wh(samples) == {}
    assert telemetry.recommend_reserve({})["reserve_pct"] is None
    assert telemetry.recommend_reserve({"d": 50})["reserve_pct"] == 90
    assert telemetry.recommend_reserve({"d": 3000})["reserve_pct"] == 10


def test_csv_round_trip(tmp_path):
    path = tmp_path / "telemetry.csv"
    r = parse_properties({"rb": 50, "ip": 100, "acip": 0}, START)
    telemetry.append(path, r)
    telemetry.append(path, r)
    rows = telemetry.load(path)
    assert rows == [(START, 100.0), (START, 100.0)]
