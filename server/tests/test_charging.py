import json
from datetime import UTC, datetime, timedelta

import pytest
from solar_server import tasks
from solar_server.config import Settings
from solar_server.store import SAMPLES, MemoryStore

NOW = datetime(2026, 10, 3, 14, tzinfo=UTC)
T = int(NOW.timestamp())
POINTS = [(NOW + timedelta(minutes=i * 5), 100.0) for i in range(288)]


def test_fresh_battery_enables_adaptive_plan_and_stale_battery_uses_fallback():
    store = MemoryStore()
    store.append(SAMPLES, {"t": T, "battery_pct": 80})
    plan = tasks.charging_plan(store, POINTS, Settings(load_w=10), NOW)
    assert plan["strategy"] == "adaptive"
    assert plan["target_pct"] == 83.7
    plan = tasks.charging_plan(store, POINTS, Settings(), NOW + timedelta(minutes=16))
    assert plan["strategy"] == "fallback"


def test_cached_forecast_replans_after_new_battery_reading_and_retains_forecast_age():
    store = MemoryStore()
    settings = Settings(load_w=20)
    store.append(SAMPLES, {"t": T, "battery_pct": 60})
    initial = tasks.charging_plan(store, POINTS, settings, NOW)
    initial.update(forecast=[[int(t.timestamp()), v] for t, v in POINTS], forecast_at=T)
    store.put_state("plan", initial)
    assert initial["windows"]
    store.append(SAMPLES, {"t": T + 300, "battery_pct": 90})
    tasks.refresh_charging_plan(store, settings, NOW + timedelta(minutes=5))
    new = store.get_state("plan")
    assert new is not None
    assert new["windows"] == []
    assert new["generated_at"] == T + 300
    assert new["forecast_at"] == T
    tasks.refresh_charging_plan(store, settings, NOW + timedelta(hours=3))
    assert store.get_state("plan") == new


@pytest.mark.parametrize(
    "kwargs", [{"charge_w": 0}, {"floor_pct": 95}, {"load_w": -1}, {"solar_day_wh": float("nan")}]
)
def test_invalid_charging_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_default_charging_speed_is_1700_w(monkeypatch):
    monkeypatch.delenv("CHARGE_W", raising=False)
    assert Settings.from_env().charge_w == 1700


def test_estimates_are_cached_between_replans_and_survive_json_storage():
    class CountingStore(MemoryStore):
        reads = 0

        def day(self, series, day):
            self.reads += 1
            return super().day(series, day)

    store = CountingStore()
    tasks.record_sample(store, {"t": T, "battery_pct": 60})
    settings = Settings(load_w=20)
    first = tasks.charging_plan(store, POINTS, settings, NOW)
    reads = store.reads
    # The Firestore state encoder round-trips through JSON.
    store.state["charging_estimates"] = json.loads(json.dumps(store.state["charging_estimates"]))
    second = tasks.charging_plan(store, POINTS, settings, NOW)
    assert second == first
    assert store.reads == reads
    tasks.charging_estimates(store, settings, T + 1800)
    assert store.reads > reads
    estimate = tasks.charging_estimates(store, Settings(charge_w=1200), T + 1801)
    assert estimate["charge_w"] == 1200


def test_unexpected_battery_drop_moves_the_plan_to_earlier_charging():
    store = MemoryStore()
    settings = Settings(load_w=100)
    dirty_then_clean = [(t, 1000.0 if t < NOW + timedelta(hours=5) else 10.0) for t, _ in POINTS]
    tasks.record_sample(store, {"t": T, "battery_pct": 80})
    initial = tasks.charging_plan(store, dirty_then_clean, settings, NOW)
    assert initial["windows"][0][0] >= T + 5 * 3600
    tasks.record_sample(store, {"t": T + 300, "battery_pct": 22})
    revised = tasks.charging_plan(store, dirty_then_clean, settings, NOW + timedelta(minutes=5))
    assert revised["windows"][0][0] < T + 3600
