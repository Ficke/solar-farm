"""Log one structured entry per problem on each collect.

Cloud Monitoring matches the ``alert`` field to policies in infra/monitoring.tf.
"""

from __future__ import annotations

import json
import sys

from solar_server.store import PLUG, SAMPLES, Store, window

PLUG_SILENT = 10 * 60
SAMPLES_STALE = 30 * 60
PLAN_STALE = 2 * 3600
NOT_CHARGING = 10 * 60
CHARGING_W = 100  # Treat sustained low plug draw as possible charging failure.
NEARLY_FULL = 95  # Exclude near-full batteries because charging tapers.


def _latest(store: Store, series: str, now: int, within: int, key: str = "t") -> int | None:
    items = window(store, series, now - within, now)
    return max((int(i.get(key, i["t"])) for i in items), default=None)


def problems(store: Store, now: int) -> dict[str, str]:
    """Return alert names and descriptions for stale data or low charging power."""
    found = {}
    if _latest(store, PLUG, now, PLUG_SILENT, key="received") is None:
        found["plug_silent"] = "No report from the plug in 10 minutes."
    if _latest(store, SAMPLES, now, SAMPLES_STALE) is None:
        found["samples_stale"] = "No Jackery or WattTime reading stored in 30 minutes."
    reports = window(store, PLUG, now - NOT_CHARGING, now)
    battery = ((store.get_state("sample") or {}).get("sample") or {}).get("battery_pct")
    if (
        len(reports) >= NOT_CHARGING // 60 - 2
        and all(r.get("on") and (r.get("w") or 0) < CHARGING_W for r in reports)
        and battery is not None
        and battery < NEARLY_FULL
    ):
        found["grid_not_charging"] = (
            f"Grid on for 10 minutes but the battery isn't charging ({battery:.0f}%)."
        )
    plan = store.get_state("plan")
    made = (plan or {}).get("generated_at")
    if not isinstance(made, int | float) or now - made > PLAN_STALE:
        found["plan_stale"] = "The grid plan is more than 2 hours old."
    return found


def check(store: Store, now: int) -> dict[str, str]:
    found = problems(store, now)
    for name, message in found.items():
        line = {"severity": "ERROR", "alert": name, "message": message}
        print(json.dumps(line), file=sys.stdout, flush=True)
    return found
