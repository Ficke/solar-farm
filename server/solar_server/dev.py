"""A local server with three days of made-up readings, for working on the dashboard.

uv run uvicorn solar_server.dev:app --port 8000
"""

from __future__ import annotations

import math
import random
import time
from datetime import UTC, datetime

from planner.plan import PACIFIC, build_plan

from solar_server.app import create_app
from solar_server.config import Settings
from solar_server.store import AOER, FORECASTS, HEALTH, PLANS, PLUG, SAMPLES, MemoryStore

STEP = 300


def _hour(t: int) -> float:
    d = datetime.fromtimestamp(t, PACIFIC)
    return d.hour + d.minute / 60


def _moer(t: int) -> float:
    # California's marginal rate is mostly gas (~950) with midday stretches
    # where curtailed solar sets it near zero.
    h = _hour(t)
    return 0.0 if 10.5 <= h < 14 else 950 + 40 * math.sin(t / 5000)


def _aoer(t: int) -> float:
    h = _hour(t)
    return 430 - 200 * max(0.0, math.sin(math.pi * (h - 7) / 12)) if 7 <= h < 19 else 430


def sample_store(now: int) -> MemoryStore:
    rng = random.Random(1)
    store = MemoryStore()
    now -= now % 60
    start = now - now % STEP - 3 * 86400
    battery = 70.0
    for t in range(start, now + 1, STEP):
        h = _hour(t)
        solar = max(0.0, 230 * math.sin(math.pi * (h - 7) / 12)) if 7 <= h < 19 else 0.0
        on = 10.5 <= h < 14
        grid = 300.0 if on and battery < 80 else 0.0
        battery = min(100.0, max(5.0, battery + (solar + grid - 60) * 5 / 60 / 30.72))
        store.append(
            SAMPLES,
            {
                "t": t,
                "battery_pct": round(battery),
                "solar_w": round(solar),
                "moer": round(_moer(t), 1),
                "moer_t": t,
                "index": 5 if on else 70,
            },
        )
        # Average CO2 arrives hourly and late; health damage a couple of hours late.
        if t % 3600 == 0 and t < now - 6 * 3600:
            store.append(AOER, {"t": t, "v": round(_aoer(t), 1)})
        if t < now - 2 * 3600:
            store.append(HEALTH, {"t": t, "v": round(_moer(t) / 40 + 2, 2)})
        if t % 1800 == 0:
            # Forecasts get the curtailment stretch roughly right, with its
            # edges off by up to an hour the further out they look.
            values = []
            for i in range(288):
                ft = t + i * STEP
                shift = rng.uniform(-1, 1) * min(1.0, i / 144) * 3600
                values.append(round(_moer(int(ft + shift)) + rng.uniform(-30, 30)))
            store.append(FORECASTS, {"t": t, "start": t, "step": STEP, "values": values})
            store.append(PLANS, {"t": t, "windows": []})
    for t in range(start, now + 1, 60):
        h = _hour(t)
        on = 10.5 <= h < 14
        reason = "peak" if 16 <= h < 21 else "plan"
        store.append(PLUG, {"t": t, "on": on, "reason": reason, "w": 280.0 if on else 0.0})

    last = now - now % 1800
    forecast = next(f for f in reversed(store.day(FORECASTS, _day(last))) if f["t"] == last)
    points = [[forecast["start"] + i * STEP, v] for i, v in enumerate(forecast["values"])]
    plan = build_plan(
        [(datetime.fromtimestamp(t, UTC), v) for t, v in points], datetime.fromtimestamp(now, UTC)
    )
    windows = plan["windows"]
    store.put_state(
        "plan",
        {
            "generated_at": last,
            "windows": windows,
            "forecast": points,
            "forecast_health": [[t, round(v / 40 + 2, 2)] for t, v in points],
            "index_now": 70,
        },
    )
    return store


def _day(t: int) -> str:
    return datetime.fromtimestamp(t, PACIFIC).date().isoformat()


class NoSources:
    """The web role never calls out; these only exist to satisfy create_app."""

    def forecast(self, hours: int, signal: str = "co2_moer") -> list:
        return []

    def signal_index(self) -> float:
        return 0.0

    def actual(self, signal: str, now: datetime) -> None:
        return None

    def history(self, signal: str, start: datetime, end: datetime) -> list:
        return []

    def jackery(self, now: object) -> None:
        return None


app = create_app(Settings(role="web"), sample_store(int(time.time())), NoSources(), clock=time.time)
