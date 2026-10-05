#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["requests>=2.32"]
# ///
"""Deploy grid-gate to a Shelly plug on the local Wi-Fi network.

    uv run tools/deploy.py
    uv run tools/deploy.py --dry-run

Read config/device.toml and Secret Manager credentials, with .env overrides.
Enable local authentication, half-hourly peak relay-off schedules and a ten-minute watchdog
that starts a stopped script. Dry runs read device state but do not write it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import requests
from requests.auth import HTTPDigestAuth

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "device" / "src" / "grid-gate.js"
SCRIPT_NAME = "grid-gate"
CHUNK = 1024
PROJECT = "solar-farm-510518"
SENSITIVE_KVS_KEYS = {"gg.plug_key", "gg.wt_auth"}
READ_ONLY_METHODS = {
    "Schedule.List",
    "Script.GetStatus",
    "Script.List",
    "Shelly.GetDeviceInfo",
    "Switch.GetStatus",
}
DEFAULT_PEAK = (960, 1260)  # minutes after local midnight, as in grid-gate.js
WATCHDOG_TIMESPEC = "0 */10 * * * *"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Shelly:
    def __init__(self, host: str, password: str | None, dry_run: bool = False):
        self.url = f"http://{host}/rpc"
        self.auth = HTTPDigestAuth("admin", password) if password else None
        self.dry_run = dry_run

    def call(self, method: str, params: dict | None = None):
        if self.dry_run and method not in READ_ONLY_METHODS:
            shown = {k: ("…" if k in ("code", "ha1") else v) for k, v in (params or {}).items()}
            if method == "KVS.Set" and shown.get("key") in SENSITIVE_KVS_KEYS:
                shown["value"] = "…"
            print(f"[dry-run] {method} {json.dumps(shown)}")
            return {}
        attempts = 3 if method in READ_ONLY_METHODS else 1
        for attempt in range(attempts):
            try:
                r = requests.post(
                    self.url,
                    json={"id": 1, "method": method, "params": params or {}},
                    auth=self.auth,
                    timeout=15,
                )
                break
            except requests.ConnectionError, requests.Timeout:
                if attempt + 1 == attempts:
                    raise
                time.sleep(attempt + 1)
        if r.status_code == 401:
            raise SystemExit(
                "The plug rejected its password. It has to match `password` in "
                "config/device.toml (or SHELLY_PASSWORD in .env). To start over, turn off "
                "authentication in the Shelly app and run deploy again."
            )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"{method}: {body['error']}")
        return body.get("result", {})


def verify_script(dev: Shelly, script_id: int) -> None:
    time.sleep(2)
    status = dev.call("Script.GetStatus", {"id": script_id})
    if status.get("running"):
        return
    detail = status.get("error_msg") or "no device error was reported"
    raise RuntimeError(f"{SCRIPT_NAME} stopped after deployment: {detail}")


def secret_value(env_name: str, secret_id: str) -> str | None:
    """Read a local override, then the deployed secret through gcloud."""
    if value := os.environ.get(env_name):
        return value
    try:
        out = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={secret_id}",
                f"--project={PROJECT}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError, subprocess.CalledProcessError:
        return None
    return out.stdout.strip() or None


def shelly_password(cfg: dict) -> str | None:
    return os.environ.get("SHELLY_PASSWORD") or cfg.get("password")


def save_password(cfg_path: Path, password: str) -> None:
    """Add the generated password to the git-ignored device.toml."""
    entry = (
        "# The plug's local password, set by deploy.py. Log in as admin.\n"
        f'password = "{password}"\n'
    )
    # Top-level keys have to come before the first [table].
    text = cfg_path.read_text()
    at = text.find("\n[")
    at = len(text) if at < 0 else at + 1
    head = text[:at].rstrip("\n")
    cfg_path.write_text(f"{head}\n\n{entry}\n{text[at:]}".rstrip("\n") + "\n")


def ensure_auth(dev: Shelly, info: dict, cfg: dict, cfg_path: Path) -> None:
    """Enable authentication to protect stored credentials and relay control."""
    password = shelly_password(cfg)
    if info.get("auth_en"):
        if not password:
            raise SystemExit(
                "The plug has a password but config/device.toml doesn't. Add it as "
                '`password = "..."` (or SHELLY_PASSWORD in .env), or turn off authentication '
                "in the Shelly app and run deploy again to set a new one."
            )
    else:
        if not password:
            password = secrets.token_urlsafe(18)
            if not dev.dry_run:
                save_password(cfg_path, password)
                print(f"Saved a new plug password in {cfg_path}.")
        # Gen2+ digest auth: ha1 = sha256("admin:<device id>:<password>").
        realm = info.get("auth_domain") or info["id"]
        ha1 = hashlib.sha256(f"admin:{realm}:{password}".encode()).hexdigest()
        dev.call("Shelly.SetAuth", {"user": "admin", "realm": realm, "ha1": ha1})
        if not dev.dry_run:
            print("Turned on the plug's local password.")
    dev.auth = HTTPDigestAuth("admin", password)


def peak_timespecs(start: int, end: int) -> list[str]:
    """Return second-59 cron specs that force the relay off during peak.

    They fire in the first peak minute and on each half hour after it, so a
    low-battery exception from the script pauses for at most one minute per
    half hour. Late-minute execution usually lets the script switch off first.
    """
    minutes = [m for m in range(start, end) if m == start or m % 30 == 0]
    by_hour: dict[int, list[int]] = {}
    for m in minutes:
        by_hour.setdefault(m // 60, []).append(m % 60)
    groups: list[tuple[list[int], list[int]]] = []
    for hour, mins in by_hour.items():
        if groups and groups[-1][1] == mins and groups[-1][0][-1] == hour - 1:
            groups[-1][0].append(hour)
        else:
            groups.append(([hour], mins))
    return [
        f"59 {','.join(map(str, mins))} "
        f"{hours[0] if len(hours) == 1 else f'{hours[0]}-{hours[-1]}'} * * *"
        for hours, mins in groups
    ]


def is_ours(job: dict, script_id: int | None) -> bool:
    """Match single-call switch-0 off or grid-gate start schedules."""
    calls = job.get("calls") or []
    if len(calls) != 1:
        return False
    method, params = calls[0].get("method"), calls[0].get("params") or {}
    if method == "Switch.Set":
        return params.get("id") == 0 and params.get("on") is False
    return method == "Script.Start" and script_id is not None and params.get("id") == script_id


def remove_schedules(dev: Shelly, script_id: int | None) -> None:
    """Remove matching schedules, including manual jobs and interrupted-deploy copies."""
    for job in dev.call("Schedule.List").get("jobs", []):
        if is_ours(job, script_id):
            dev.call("Schedule.Delete", {"id": job["id"]})


def add_schedule(dev: Shelly, timespec: str, method: str, params: dict) -> None:
    dev.call(
        "Schedule.Create",
        {"enable": True, "timespec": timespec, "calls": [{"method": method, "params": params}]},
    )


def kvs_settings(cfg: dict) -> dict[str, str]:
    kv = {"gg.plan_url": cfg["plan_url"]}
    if cfg.get("report_url"):
        kv["gg.report_url"] = cfg["report_url"]
    if "/plug/" in cfg["plan_url"] or cfg.get("report_url"):
        key = secret_value("PLUG_KEY", "plug-key")
        if not key:
            raise SystemExit(
                "The plan URL is the solar-edge service, which needs the plug key. Set "
                "PLUG_KEY in .env, or run `gcloud auth login` so it's read from Secret Manager."
            )
        kv["gg.plug_key"] = key
    user = secret_value("WATTTIME_USERNAME", "watttime-username")
    pw = secret_value("WATTTIME_PASSWORD", "watttime-password")
    if user and pw:
        kv["gg.wt_auth"] = base64.b64encode(f"{user}:{pw}".encode()).decode()
    else:
        print(
            "WattTime credentials unavailable; deploying without the live-index fallback.",
            file=sys.stderr,
        )
    tuning = cfg.get("tuning", {})
    if tuning:
        kv["gg.cfg"] = json.dumps(tuning, separators=(",", ":"))
    return kv


def deploy(dev: Shelly, cfg: dict, cfg_path: Path) -> None:
    info = dev.call("Shelly.GetDeviceInfo")
    model, dev_id, fw = info.get("model", "?"), info.get("id", "?"), info.get("ver", "?")
    print(f"Connected to {model} ({dev_id}), firmware {fw}")
    ensure_auth(dev, info, cfg, cfg_path)

    # The script reads local time for the peak block, so pin the timezone.
    dev.call(
        "Sys.SetConfig",
        {"config": {"location": {"tz": cfg.get("timezone", "America/Los_Angeles")}}},
    )
    # Keep the relay where it was across reboots; the script takes over within a minute.
    dev.call(
        "Switch.SetConfig",
        {"id": 0, "config": {"initial_state": "restore_last", "auto_on": False, "auto_off": False}},
    )

    for key, value in kvs_settings(cfg).items():
        dev.call("KVS.Set", {"key": key, "value": value})

    scripts = dev.call("Script.List").get("scripts", [])
    existing = next((s for s in scripts if s.get("name") == SCRIPT_NAME), None)

    # Remove the old watchdog before uploading so it cannot start partial code.
    remove_schedules(dev, existing["id"] if existing else None)
    tuning = cfg.get("tuning", {})
    peak = (tuning.get("peakStart", DEFAULT_PEAK[0]), tuning.get("peakEnd", DEFAULT_PEAK[1]))
    for spec in peak_timespecs(*peak):
        add_schedule(dev, spec, "Switch.Set", {"id": 0, "on": False})

    if existing:
        script_id = existing["id"]
        if existing.get("running"):
            dev.call("Script.Stop", {"id": script_id})
    else:
        script_id = dev.call("Script.Create", {"name": SCRIPT_NAME}).get("id", 1)

    code = SCRIPT_PATH.read_text()
    for i in range(0, len(code), CHUNK):
        dev.call("Script.PutCode", {"id": script_id, "code": code[i : i + CHUNK], "append": i > 0})
    dev.call("Script.SetConfig", {"id": script_id, "config": {"enable": True}})
    dev.call("Script.Start", {"id": script_id})
    add_schedule(dev, WATCHDOG_TIMESPEC, "Script.Start", {"id": script_id})
    if not dev.dry_run:
        verify_script(dev, script_id)
    print(f"Deployed {SCRIPT_NAME} as script {script_id} ({len(code)} bytes).")
    print(
        f"Schedules: relay off every minute from {peak[0] // 60}:{peak[0] % 60:02d} to "
        f"{peak[1] // 60}:{peak[1] % 60:02d}, script restarted if stopped."
    )
    print(f"Status: http://{cfg['host']}/script/{script_id}/status (user admin)")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", default=str(ROOT / "config" / "device.toml"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    load_env(ROOT / ".env")
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(
            f"Missing {cfg_path}. Copy config/device.example.toml and fill it in.", file=sys.stderr
        )
        return 1
    cfg = tomllib.loads(cfg_path.read_text())
    dev = Shelly(cfg["host"], None, dry_run=args.dry_run)
    deploy(dev, cfg, cfg_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
