#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["requests>=2.32"]
# ///
"""Show what the plug is doing: relay state, why, power draw and recent charges."""

from __future__ import annotations

import argparse
import json
import tomllib
from datetime import datetime
from pathlib import Path

import requests
from deploy import (  # ty: ignore[unresolved-import]
    ROOT,
    SCRIPT_NAME,
    Shelly,
    load_env,
    shelly_password,
)


def fmt(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %H:%M") if ts else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config" / "device.toml"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    cfg = tomllib.loads(Path(args.config).read_text())
    dev = Shelly(cfg["host"], shelly_password(cfg))

    sw = dev.call("Switch.GetStatus", {"id": 0})
    print(
        f"Relay: {'ON' if sw.get('output') else 'off'}  {sw.get('apower', 0):.0f} W  "
        f"total {sw.get('aenergy', {}).get('total', 0) / 1000:.2f} kWh"
    )

    scripts = dev.call("Script.List").get("scripts", [])
    script = next((s for s in scripts if s.get("name") == SCRIPT_NAME), None)
    if not script:
        print("grid-gate is not installed. Run tools/deploy.py.")
        return 1
    if not script.get("running"):
        print("grid-gate is installed but not running.")
        return 1
    r = requests.get(
        f"http://{cfg['host']}/script/{script['id']}/status", auth=dev.auth, timeout=10
    )
    st = r.json()
    print(f"Reason: {st['reason']}   live index: {st['index']}")
    windows = ", ".join(f"{fmt(s)} to {fmt(e)}" for s, e in st["planWindows"])
    print(f"Plan from {fmt(st['planGeneratedAt'])}: {windows or 'no windows'}")
    print("Recent grid charges:")
    for s in st["sessions"][-7:]:
        print(f"  {fmt(s['start'])} to {fmt(s['end'])}  {s['wh']} Wh")
    if args.json:
        print(json.dumps(st, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
