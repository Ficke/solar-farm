"""FirestoreStore against the Firestore emulator.

Skipped unless FIRESTORE_EMULATOR_HOST is set; `just test-firestore` starts
the emulator and runs these.
"""

import os
import uuid

import pytest
from solar_server import tasks
from solar_server.store import FORECASTS, MIX, PLANS, PLUG, SAMPLES, FirestoreStore
from test_app import AUTH, NOW, make

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="needs the Firestore emulator"
)
KEY = {"X-Plug-Key": "k3y"}


@pytest.fixture
def store():
    # A fresh project per test keeps tests apart without clearing anything.
    return FirestoreStore(project=f"test-{uuid.uuid4().hex[:12]}")


def test_every_series_round_trips_through_the_tasks(store):
    edge, _ = make("edge", store=store)
    assert edge.post("/tasks/plan", headers=AUTH).status_code == 200
    fallback = edge.get("/plug/plan", headers=KEY).json()
    assert fallback["strategy"] == "fallback"
    assert fallback["windows"] == [[NOW + 18 * 3600, NOW + 19 * 3600]]
    assert edge.post("/tasks/collect", headers=AUTH).status_code == 200
    plan = edge.get("/plug/plan", headers=KEY).json()
    assert plan["strategy"] == "adaptive"
    assert plan["target_pct"] == 83.7
    assert plan["windows"] and plan["windows"] != fallback["windows"]
    report = {"t": NOW, "on": True, "reason": "plan", "w": 410.2, "wh": 1200}
    assert edge.post("/plug/report", json=report, headers=KEY).status_code == 204

    day = "2026-10-04"
    (sample,) = store.day(SAMPLES, day)
    assert sample["solar_w"] == 120.0 and sample["moer_t"] == NOW - 300
    assert store.day(PLUG, day)[0]["w"] == 410.2
    assert store.day(PLANS, day) == [
        {"t": NOW, "windows": [{"s": s, "e": e} for s, e in p["windows"]]} for p in (fallback, plan)
    ]
    (forecast,) = store.day(FORECASTS, day)
    assert len(forecast["values"]) == 288
    assert sorted(r["t"] for r in store.day(MIX, day)) == [NOW - 7200, NOW - 600]

    # The plan keeps its nested arrays, which Firestore can't store directly.
    stored = store.get_state("plan")
    assert stored is not None and stored["windows"] == plan["windows"]
    # Replanning through the JSON-encoded estimate cache preserves solar shape.
    assert edge.post("/tasks/collect", headers=AUTH).status_code == 200
    assert edge.get("/plug/plan", headers=KEY).json() == plan

    web, _ = make("web", store=store)
    now = web.get("/api/now").json()
    assert now["sample"] == sample
    assert now["plug"]["w"] == 410.2
    assert now["plan"]["windows"] == plan["windows"]
    tl = web.get("/api/timeline").json()
    assert len(tl["forecast"]) == 288 and len(tl["mix"]) == 2


def test_rows_already_stored_are_skipped(store):
    rows = [{"t": NOW - 600, "solar": 0, "gas": 15000}, {"t": NOW, "solar": 12.5, "gas": None}]
    store.extend(MIX, rows)
    store.extend(MIX, [*rows, {"t": NOW + 300, "solar": 1, "gas": 2}])
    assert [r["t"] for r in store.day(MIX, "2026-10-04")] == [NOW - 600, NOW, NOW + 300]


def test_running_totals_carry_across_requests(store):
    for i in range(7):
        tasks.record_plug(
            store, {"t": NOW - 3600 + i * 600, "on": True, "reason": "plan", "w": 60.0}
        )
    state = store.get_state("plug")
    assert state is not None
    assert state["today"] == {"day": "2026-10-04", "wh": 60.0, "last": [NOW, 60.0]}
    assert store.get_state("missing") is None
    assert store.day(PLUG, "1999-01-01") == []


def test_day_totals_round_trip(store):
    store.put_total("2026-10-04", {"day": "2026-10-04", "load_lb": 0.4})
    assert store.totals(["2026-10-03", "2026-10-04"]) == [{"day": "2026-10-04", "load_lb": 0.4}]
