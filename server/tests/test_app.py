from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from planner.jackery import Reading
from solar_server.app import create_app
from solar_server.config import Settings
from solar_server.store import FORECASTS, MIX, PLANS, PLUG, SAMPLES, MemoryStore

NOW = 1791158400  # Sat 4 Oct 2026, 17:00 Pacific
SCHED = "solar-scheduler@p.iam.gserviceaccount.com"


class FakeSources:
    def __init__(self, jackery: bool = True, fail_index: bool = False, actuals: bool = True):
        self.with_jackery = jackery
        self.fail_index = fail_index
        self.actuals = actuals

    def forecast(self, hours, signal="co2_moer"):
        start = NOW - NOW % 300
        # dirty now, clean from +18h onwards
        return [
            (datetime.fromtimestamp(start + i * 300, UTC), 900.0 if i < 216 else 150.0)
            for i in range(hours * 12)
        ]

    def signal_index(self):
        if self.fail_index:
            raise RuntimeError("watttime down")
        return 82.0

    def actual(self, signal, now):
        if not self.actuals:
            raise RuntimeError("watttime down")
        return (datetime.fromtimestamp(NOW - 300, UTC), 880.0)

    def mix(self, day, now):
        return [{"t": t, "solar": 0, "gas": 15000} for t in (NOW - 7200, NOW - 600, NOW + 300)]

    def jackery(self, now):
        if not self.with_jackery:
            return None
        return Reading(now, 81.0, 120.0, 0.0, 0.0, 90.0, {})


def verifier(token, audience):
    if token != "good":
        raise ValueError("bad signature")
    assert audience == "https://testserver"
    return {"email": SCHED, "email_verified": True}


def make(role, store=None, sources=None):
    s = Settings(role=role, plug_key="k3y", scheduler_sa=SCHED)
    store = store or MemoryStore()
    app = create_app(s, store, sources or FakeSources(), verify=verifier, clock=lambda: NOW)
    return TestClient(app, base_url="https://testserver"), store


AUTH = {"Authorization": "Bearer good"}


def test_tasks_require_the_scheduler_token():
    c, _ = make("edge")
    assert c.post("/tasks/collect").status_code == 401
    assert c.post("/tasks/collect", headers={"Authorization": "Bearer forged"}).status_code == 401
    assert c.post("/tasks/collect", headers=AUTH).status_code == 200


def test_scheduler_token_for_someone_else_is_refused():
    s = Settings(role="edge", plug_key="k3y", scheduler_sa=SCHED)
    app = create_app(
        s,
        MemoryStore(),
        FakeSources(),
        verify=lambda t, a: {"email": "intruder@x.com", "email_verified": True},
        clock=lambda: NOW,
    )
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/tasks/collect", headers=AUTH).status_code == 403


def test_collect_stores_one_sample_with_every_source():
    c, store = make("edge")
    body = c.post("/tasks/collect", headers=AUTH).json()
    assert body == {
        "t": NOW,
        "moer": 880.0,
        "moer_t": NOW - 300,
        "index": 82.0,
        "battery_pct": 81.0,
        "solar_w": 120.0,
        "ac_input_w": 0.0,
        "output_w": 90.0,
    }
    assert store.day(SAMPLES, "2026-10-04") == [body]


def test_collect_keeps_going_when_a_source_fails():
    c, _ = make("edge", sources=FakeSources(jackery=False, fail_index=True))
    body = c.post("/tasks/collect", headers=AUTH).json()
    assert body["moer"] == 880.0
    assert "index" not in body and "battery_pct" not in body

    c, _ = make("edge", sources=FakeSources(actuals=False))
    body = c.post("/tasks/collect", headers=AUTH).json()
    assert "moer" not in body and body["battery_pct"] == 81.0


def test_plan_task_feeds_the_plug_without_the_forecast():
    c, store = make("edge")
    assert c.get("/plug/plan", headers={"X-Plug-Key": "k3y"}).status_code == 503
    c.post("/tasks/plan", headers=AUTH)
    assert len(store.get_state("plan")["forecast"]) == 288

    plan = c.get("/plug/plan", headers={"X-Plug-Key": "k3y"}).json()
    assert not any(k.startswith("forecast") for k in plan)
    assert plan["generated_at"] == NOW
    assert plan["index_now"] == 82.0
    # 4 clean hours, all in the cheap stretch 18 h out
    assert plan["windows"] == [[NOW + 18 * 3600, NOW + 22 * 3600]]

    # Every plan and its forecast are kept, not just the latest.
    assert store.day(PLANS, "2026-10-04") == [
        {"t": NOW, "windows": [{"s": NOW + 18 * 3600, "e": NOW + 22 * 3600}]}
    ]
    (snap,) = store.day(FORECASTS, "2026-10-04")
    assert snap["t"] == NOW and snap["step"] == 300 and len(snap["values"]) == 288


def test_grid_mix_is_stored_once_per_row():
    c, store = make("edge")
    c.post("/tasks/collect", headers=AUTH)
    # A reading keeps the last hour; a plan fills in the last day.
    assert [r["t"] for r in store.day(MIX, "2026-10-04")] == [NOW - 600]
    c.post("/tasks/plan", headers=AUTH)
    c.post("/tasks/collect", headers=AUTH)
    assert [r["t"] for r in store.day(MIX, "2026-10-04")] == [NOW - 600, NOW - 7200]

    web, _ = make("web", store=store)
    tl = web.get("/api/timeline").json()
    assert tl["mix"] == [
        {"t": NOW - 7200, "solar": 0, "gas": 15000},
        {"t": NOW - 600, "solar": 0, "gas": 15000},
    ]


def test_accuracy_compares_the_forecast_made_hours_earlier():
    store = MemoryStore()
    start = NOW - 12 * 3600
    # Two forecasts: one 12 h ago saying 500, one 2 h ago saying 100.
    for made, value in ((start, 500), (NOW - 2 * 3600, 100)):
        store.append(FORECASTS, {"t": made, "start": made, "step": 300, "values": [value] * 288})
    for t in (NOW - 3600, NOW):
        store.append(SAMPLES, {"t": t, "moer": 400.0})
    c, _ = make("web", store=store)

    six = c.get("/api/accuracy?lead_hours=6").json()
    assert six["points"] == [[NOW - 3600, 400.0, 500], [NOW, 400.0, 500]]
    assert six["error"] == 100 and six["compared"] == 2

    one = c.get("/api/accuracy?lead_hours=1").json()
    assert one["points"][-1] == [NOW, 400.0, 100]
    # A reading two hours after the newer forecast was made can use it.
    assert one["points"][0] == [NOW - 3600, 400.0, 100]


@pytest.mark.parametrize("key", [None, "", "wrong"])
def test_plug_endpoints_need_the_key(key):
    c, _ = make("edge")
    headers = {} if key is None else {"X-Plug-Key": key}
    assert c.get("/plug/plan", headers=headers).status_code == 401
    assert (
        c.post(
            "/plug/report", json={"t": NOW, "on": True, "reason": "plan"}, headers=headers
        ).status_code
        == 401
    )


def test_plug_report_is_stored():
    c, store = make("edge")
    r = c.post(
        "/plug/report",
        json={"t": NOW, "on": True, "reason": "plan", "w": 410.2, "wh": 1200, "index": None},
        headers={"X-Plug-Key": "k3y"},
    )
    assert r.status_code == 204
    assert store.day(PLUG, "2026-10-04") == [
        {"t": NOW, "on": True, "reason": "plan", "w": 410.2, "wh": 1200.0, "received": NOW}
    ]


def test_roles_only_expose_their_own_routes():
    web, _ = make("web")
    edge, _ = make("edge")
    assert web.post("/tasks/collect", headers=AUTH).status_code in (404, 405)
    assert web.get("/plug/plan", headers={"X-Plug-Key": "k3y"}).status_code == 404
    assert edge.get("/api/now").status_code == 404


def test_dashboard_api_summarizes_the_day():
    store = MemoryStore()
    # 17:00 Pacific; samples every 5 min from 12:00 with 100 W of sun, plug at 400 W for an hour
    for i in range(61):
        t = NOW - 5 * 3600 + i * 300
        store.append(
            SAMPLES, {"t": t, "battery_pct": 70 + i * 0.2, "solar_w": 100.0, "moer": 300.0}
        )
    for i in range(61):
        t = NOW - 2 * 3600 + i * 60
        store.append(PLUG, {"t": t, "on": True, "reason": "plan", "w": 400.0})
    store.put_state(
        "plan",
        {
            "generated_at": NOW - 60,
            "windows": [[NOW, NOW + 3600]],
            "forecast": [[NOW, 200.0], [NOW + 300, 210.0]],
        },
    )
    web, _ = make("web", store=store)

    now = web.get("/api/now").json()
    assert now["sample"]["t"] == NOW
    assert now["plug"]["w"] == 400.0
    assert now["today"] == {"solar_wh": 500, "grid_wh": 400}
    assert now["plan"]["windows"] == [[NOW, NOW + 3600]]

    tl = web.get("/api/timeline", params={"past_hours": 3}).json()
    assert tl["samples"][0]["t"] == NOW - 3 * 3600
    assert len(tl["plug"]) == 61
    assert tl["forecast"] == [[NOW, 200.0], [NOW + 300, 210.0]]

    daily = web.get("/api/daily", params={"days": 3}).json()
    assert daily["days"] == [
        {"day": "2026-10-04", "solar_wh": 500, "grid_wh": 400, "battery_peak_pct": 82.0}
    ]
    assert daily["reserve"]["reserve_pct"] is None  # today isn't a full day yet
