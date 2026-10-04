import json

from solar_server import health
from solar_server.store import PLUG, SAMPLES, MemoryStore

NOW = 1791158400  # Sat 4 Oct 2026, 17:00 Pacific


def healthy() -> MemoryStore:
    store = MemoryStore()
    store.append(PLUG, {"t": NOW - 60, "on": False, "reason": "peak", "received": NOW - 59})
    store.append(SAMPLES, {"t": NOW - 300, "moer": 880.0})
    store.put_state("plan", {"generated_at": NOW - 1800, "windows": []})
    return store


def test_nothing_to_report_when_everything_is_fresh(capsys):
    assert health.check(healthy(), NOW) == {}
    assert capsys.readouterr().out == ""


def test_each_quiet_part_is_its_own_alert(capsys):
    store = healthy()
    later = NOW + 3 * 3600
    found = health.check(store, later)
    assert set(found) == {"plug_silent", "samples_stale", "plan_stale"}
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {line["alert"] for line in lines} == set(found)
    assert all(line["severity"] == "ERROR" for line in lines)


def test_thresholds():
    store = healthy()
    assert "plug_silent" in health.problems(store, NOW - 59 + 601)
    assert "plug_silent" not in health.problems(store, NOW - 59 + 540)
    assert "samples_stale" in health.problems(store, NOW - 300 + 1801)
    assert "plan_stale" in health.problems(store, NOW - 1800 + 7201)
    assert "plan_stale" not in health.problems(store, NOW - 1800 + 7199)


def test_no_plan_at_all_is_stale():
    store = healthy()
    store.state.clear()
    assert "plan_stale" in health.problems(store, NOW)
