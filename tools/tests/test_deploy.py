import base64
import subprocess

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
