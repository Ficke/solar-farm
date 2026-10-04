import base64
import subprocess

import pytest

from tools import deploy


def test_secret_value_prefers_environment(monkeypatch):
    monkeypatch.setenv("PLUG_KEY", "local-key")

    def unexpected_run(*args, **kwargs):
        raise AssertionError("gcloud should not run when an override exists")

    monkeypatch.setattr(subprocess, "run", unexpected_run)

    assert deploy.secret_value("PLUG_KEY", "plug-key") == "local-key"


def test_secret_value_reads_secret_manager(monkeypatch):
    monkeypatch.delenv("WATTTIME_USERNAME", raising=False)

    def fake_run(command, **kwargs):
        assert "--secret=watttime-username" in command
        assert f"--project={deploy.PROJECT}" in command
        return subprocess.CompletedProcess(command, 0, "grid-user\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert deploy.secret_value("WATTTIME_USERNAME", "watttime-username") == "grid-user"


def test_kvs_settings_loads_all_deployed_secrets(monkeypatch):
    secrets = {
        "plug-key": "device-key",
        "watttime-username": "grid-user",
        "watttime-password": "grid-password",
    }
    monkeypatch.setattr(deploy, "secret_value", lambda env_name, secret_id: secrets[secret_id])

    settings = deploy.kvs_settings(
        {
            "plan_url": "https://example.com/plug/plan",
            "report_url": "https://example.com/plug/report",
        }
    )

    assert settings["gg.plug_key"] == "device-key"
    assert base64.b64decode(settings["gg.wt_auth"]).decode() == "grid-user:grid-password"


def test_dry_run_redacts_secret_values(capsys):
    shelly = deploy.Shelly("192.0.2.1", None, dry_run=True)

    shelly.call("KVS.Set", {"key": "gg.wt_auth", "value": "encoded-secret"})

    output = capsys.readouterr().out
    assert "gg.wt_auth" in output
    assert "encoded-secret" not in output


def test_read_only_calls_retry_connection_failures(monkeypatch):
    attempts = 0

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"model": "plug"}}

    def fake_post(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise deploy.requests.ConnectionError("offline")
        return Response()

    monkeypatch.setattr(deploy.requests, "post", fake_post)
    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)

    result = deploy.Shelly("192.0.2.1", None).call("Shelly.GetDeviceInfo")

    assert result == {"model": "plug"}
    assert attempts == 3


def test_deployment_verification_reports_script_failure(monkeypatch):
    class Device(deploy.Shelly):
        def __init__(self):
            pass

        def call(self, method: str, params: dict | None = None):
            assert method == "Script.GetStatus"
            assert params == {"id": 1}
            return {"running": False, "error_msg": "Too many calls in progress"}

    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="Too many calls in progress"):
        deploy.verify_script(Device(), 1)


def test_peak_timespecs_fire_late_in_each_peak_minute():
    assert deploy.peak_timespecs(960, 1260) == ["59 * 16-20 * * *"]
    assert deploy.peak_timespecs(960, 1020) == ["59 * 16 * * *"]
    assert deploy.peak_timespecs(990, 1050) == ["59 30-59 16 * * *", "59 0-29 17 * * *"]
    assert deploy.peak_timespecs(990, 1200) == [
        "59 30-59 16 * * *",
        "59 * 17-19 * * *",
    ]
    assert deploy.peak_timespecs(960, 1215) == ["59 * 16-19 * * *", "59 0-14 20 * * *"]
    assert deploy.peak_timespecs(960, 961) == ["59 0 16 * * *"]
    assert deploy.peak_timespecs(960, 960) == []


class FakePlug(deploy.Shelly):
    """Record calls and replay a small device state."""

    def __init__(self, auth_en=False, jobs=(), kvs=None):
        super().__init__("192.0.2.1", None)
        self.auth_en = auth_en
        self.jobs = {j: {"id": j} for j in jobs}
        self.kvs = dict(kvs or {})
        self.calls = []

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        match method:
            case "Shelly.GetDeviceInfo":
                return {"id": "shellyplugusg4-abc", "model": "S4PL", "auth_en": self.auth_en}
            case "KVS.Get":
                if params["key"] not in self.kvs:
                    raise RuntimeError("not found")
                return {"value": self.kvs[params["key"]]}
            case "KVS.Set":
                self.kvs[params["key"]] = params["value"]
            case "Schedule.List":
                return {"jobs": list(self.jobs.values())}
            case "Schedule.Delete":
                del self.jobs[params["id"]]
            case "Schedule.Create":
                job_id = max(self.jobs, default=0) + 1
                self.jobs[job_id] = {"id": job_id, **params}
                return {"id": job_id}
            case "Script.List":
                return {"scripts": [{"id": 1, "name": deploy.SCRIPT_NAME, "running": True}]}
            case "Script.GetStatus":
                return {"running": True}
        return {}


def test_first_deploy_sets_a_password_and_saves_it(tmp_path, monkeypatch):
    monkeypatch.delenv("SHELLY_PASSWORD", raising=False)
    cfg_path = tmp_path / "device.toml"
    cfg_path.write_text('host = "192.0.2.1"\n\n[tuning]\nthreshold = 25\n')
    plug = FakePlug()

    deploy.ensure_auth(plug, plug.call("Shelly.GetDeviceInfo"), {}, cfg_path)

    saved = deploy.tomllib.loads(cfg_path.read_text())
    password = saved["password"]
    assert saved["tuning"] == {"threshold": 25}
    ha1 = deploy.hashlib.sha256(f"admin:shellyplugusg4-abc:{password}".encode()).hexdigest()
    assert ("Shelly.SetAuth", {"user": "admin", "realm": "shellyplugusg4-abc", "ha1": ha1}) in (
        plug.calls
    )
    assert plug.auth is not None
    assert plug.auth.password == password


def test_existing_password_is_used_without_resetting_it(tmp_path, monkeypatch):
    monkeypatch.delenv("SHELLY_PASSWORD", raising=False)
    plug = FakePlug(auth_en=True)

    deploy.ensure_auth(plug, {"id": "x", "auth_en": True}, {"password": "pw"}, tmp_path / "t")

    assert not any(m == "Shelly.SetAuth" for m, _ in plug.calls)
    assert plug.auth is not None
    assert plug.auth.password == "pw"


def test_password_protected_plug_without_a_known_password_stops(tmp_path, monkeypatch):
    monkeypatch.delenv("SHELLY_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="password"):
        deploy.ensure_auth(FakePlug(), {"id": "x", "auth_en": True}, {}, tmp_path / "t")


def test_deploy_replaces_its_own_schedules_and_keeps_others(monkeypatch):
    monkeypatch.setenv("SHELLY_PASSWORD", "pw")
    monkeypatch.setattr(deploy, "kvs_settings", lambda cfg: {})
    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)
    off = [{"method": "Switch.Set", "params": {"id": 0, "on": False}}]
    restart = [{"method": "Script.Start", "params": {"id": 1}}]
    plug = FakePlug(auth_en=True)
    # Include duplicate deploy schedules and unrelated manual schedules.
    plug.jobs = {
        1: {"id": 1, "calls": off},
        2: {"id": 2, "calls": restart},
        3: {"id": 3, "calls": off},
        4: {"id": 4, "calls": restart},
        7: {"id": 7, "calls": [{"method": "Switch.Set", "params": {"id": 0, "on": True}}]},
        8: {"id": 8, "calls": [{"method": "Script.Start", "params": {"id": 2}}]},
    }

    deploy.deploy(plug, {"host": "192.0.2.1"}, deploy.Path("unused"))

    assert set(plug.jobs) == {7, 8, 9, 10}
    assert plug.jobs[9]["timespec"] == "59 * 16-20 * * *"
    assert plug.jobs[9]["calls"] == off
    assert plug.jobs[10]["timespec"] == deploy.WATCHDOG_TIMESPEC
    assert plug.jobs[10]["calls"] == restart

    # The old watchdog is gone before the script is stopped and re-uploaded.
    methods = [m for m, _ in plug.calls]
    assert methods.index("Schedule.Delete") < methods.index("Script.Stop")

    # Deploying again leaves the same two, not four.
    deploy.deploy(plug, {"host": "192.0.2.1"}, deploy.Path("unused"))
    assert len(plug.jobs) == 4
