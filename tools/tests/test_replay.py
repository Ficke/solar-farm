from datetime import datetime, time, timedelta

from planner.plan import PACIFIC
from solar_server.config import Settings

from tools import replay

DAY = datetime(2026, 10, 20, tzinfo=PACIFIC)


def recording() -> dict:
    """Two days: 50 W load, no solar, 0 lb/MWh from noon to 2 pm, else 900."""
    start = int((DAY - timedelta(days=1)).timestamp())
    samples, forecasts = [], []
    for i in range(2 * 288):
        t = start + i * 300
        hour = datetime.fromtimestamp(t, PACIFIC).hour
        rate = 0.0 if 12 <= hour < 14 else 900.0
        samples.append({"t": t, "battery_pct": 60.0, "solar_w": 0.0, "moer": rate, "moer_t": t})
        if i % 6 == 0:
            values = [
                0 if 12 <= datetime.fromtimestamp(t + k * 300, PACIFIC).hour < 14 else 900
                for k in range(288)
            ]
            forecasts.append({"t": t, "start": t, "step": 300, "values": values})
    plug = [{"t": s["t"], "on": False, "w": 0.0} for s in samples]
    return {"samples": samples, "plug": plug, "forecasts": forecasts, "battery": None}


def test_replay_charges_in_the_clean_hours(monkeypatch):
    # A steady load the battery model can't measure from flat readings: patch it.
    monkeypatch.setattr(replay, "load_points", lambda s, p, b: [(x["t"], 50.0) for x in s])
    start = int(datetime.combine(DAY.date() - timedelta(days=1), time(16), PACIFIC).timestamp())
    (row,) = replay.replay(recording(), start, start + 86400, Settings())
    assert row["day"] == DAY.date().isoformat()
    assert row["grid_wh"] > 1000
    assert row["dirty_wh"] < row["grid_wh"] / 2
    assert row["pct_4pm"] > 90
