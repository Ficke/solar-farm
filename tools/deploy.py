#!/usr/bin/env python3
"""Push grid-gate.js and its settings to the Shelly plug over your home Wi-Fi.

    python tools/deploy.py            # uses config/device.toml and .env
    python tools/deploy.py --dry-run  # show what would be sent

Talks to the plug's local JSON-RPC API (http://<host>/rpc). Run it from a
machine on the same network as the plug.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tomllib
from pathlib import Path

import requests
from requests.auth import HTTPDigestAuth

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "device" / "src" / "grid-gate.js"
SCRIPT_NAME = "grid-gate"
CHUNK = 1024


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
        if self.dry_run and method not in ("Script.List", "Shelly.GetDeviceInfo"):
            shown = {k: ("…" if k == "code" else v) for k, v in (params or {}).items()}
            print(f"[dry-run] {method} {json.dumps(shown)}")
            return {}
        r = requests.post(
            self.url, json={"id": 1, "method": method, "params": params or {}}, auth=self.auth, timeout=15
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"{method}: {body['error']}")
        return body.get("result", {})


def kvs_settings(cfg: dict) -> dict[str, str]:
    kv = {"gg.plan_url": cfg["plan_url"]}
    user, pw = os.environ.get("WATTTIME_USER"), os.environ.get("WATTTIME_PASSWORD")
    if user and pw:
        kv["gg.wt_auth"] = base64.b64encode(f"{user}:{pw}".encode()).decode()
    tuning = cfg.get("tuning", {})
    if tuning:
        kv["gg.cfg"] = json.dumps(tuning, separators=(",", ":"))
    return kv


def deploy(dev: Shelly, cfg: dict) -> None:
    info = dev.call("Shelly.GetDeviceInfo")
    print(f"Connected to {info.get('model', '?')} ({info.get('id', '?')}), firmware {info.get('ver', '?')}")

    # The script reads local time for the peak block, so pin the timezone.
    dev.call("Sys.SetConfig", {"config": {"location": {"tz": cfg.get("timezone", "America/Los_Angeles")}}})
    # Keep the relay where it was across reboots; the script takes over within a minute.
    dev.call("Switch.SetConfig", {"id": 0, "config": {"initial_state": "restore_last", "auto_on": False, "auto_off": False}})

    for key, value in kvs_settings(cfg).items():
        dev.call("KVS.Set", {"key": key, "value": value})

    scripts = dev.call("Script.List").get("scripts", [])
    existing = next((s for s in scripts if s.get("name") == SCRIPT_NAME), None)
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
    print(f"Deployed {SCRIPT_NAME} as script {script_id} ({len(code)} bytes).")
    print(f"Status: http://{cfg['host']}/script/{script_id}/status")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(ROOT / "config" / "device.toml"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    load_env(ROOT / ".env")
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"Missing {cfg_path}. Copy config/device.example.toml and fill it in.", file=sys.stderr)
        return 1
    cfg = tomllib.loads(cfg_path.read_text())
    dev = Shelly(cfg["host"], os.environ.get("SHELLY_PASSWORD") or None, dry_run=args.dry_run)
    deploy(dev, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
