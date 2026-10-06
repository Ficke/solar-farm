"""Serve three days of synthetic readings for local dashboard development.

uv run uvicorn solar_server.dev:app --port 8000
"""

from __future__ import annotations

import math
import random
import time
from datetime import UTC, datetime

from planner.adaptive import build_adaptive_plan
from planner.plan import PACIFIC

from solar_server import tasks, totals
from solar_server.app import create_app
from solar_server.config import Settings
from solar_server.store import FORECASTS, MIX, PLANS, PRICES, MemoryStore

STEP = 300


def _hour(t: int) -> float:
    d = datetime.fromtimestamp(t, PACIFIC)
    return d.hour + d.minute / 60


def _moer(t: int) -> float:
    # Approximate gas-dominated rates with a midday solar-curtailment interval.
    h = _hour(t)
    return 0.0 if 10.5 <= h < 14 else 950 + 40 * math.sin(t / 5000)


def _prices(t: int) -> dict:
    # About $45 overnight and $30 midday, with the north above the south
    # while the lines between them are full in the morning.
    h = _hour(t)
    sun = max(0.0, math.sin(math.pi * (h - 7) / 12)) if 7 <= h < 19 else 0.0
    south = 45 - 18 * sun + 25 * math.exp(-(((h - 19) / 1.5) ** 2)) + 3 * math.sin(t / 900)
    north = south + (10 if 8.5 <= h < 10 else 1)
    return {"t": t, "np15": round(north, 2), "sp15": round(south, 2)}


def _mix(t: int) -> dict:
    # Approximate an October mix with midday solar and evening battery discharge.
    h = _hour(t)
    sun = max(0.0, math.sin(math.pi * (h - 7) / 12)) if 7 <= h < 19 else 0.0
    batteries = -4000 * sun if sun else (6000 if 17 <= h < 22 else 800)
    demand = 24000 + 6000 * math.exp(-(((h - 19) / 3) ** 2))
    fixed = 2228 + 780 + 600 + 2500 + 900 + 5000
    solar = 15000 * sun
    gas = max(2500.0, demand - fixed - solar - max(0.0, batteries))
    return {
        "t": t,
        "solar": round(solar - 50),
        "wind": 900,
        "geothermal": 780,
        "biomass": 190,
        "biogas": 155,
        "small_hydro": 230,
        "coal": 3,
        "nuclear": 2228,
        "gas": round(gas),
        "large_hydro": 2500,
        "batteries": round(batteries),
        "imports": 5000,
        "other": 0,
    }


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
        load = 60.0 + 40 * rng.random() + (90.0 if 18 <= h < 23 else 0.0)
        battery = min(100.0, max(5.0, battery + (solar + grid - load) * 5 / 60 / 30.72))
        tasks.record_sample(
            store,
            {
                "t": t,
                "battery_pct": round(battery),
                "solar_w": round(solar),
                "output_w": round(load),
                "moer": round(_moer(t), 1),
                "moer_t": t,
                "index": 5 if on else 70,
            },
        )
        store.append(MIX, _mix(t))
        store.append(PRICES, _prices(t))
        if t % 1800 == 0:
            # Increase timing uncertainty with forecast lead time.
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
        tasks.record_plug(store, {"t": t, "on": on, "reason": reason, "w": 280.0 if on else 0.0})

    totals.update(store, now)

    last = now - now % 1800
    forecast = next(f for f in reversed(store.day(FORECASTS, _day(last))) if f["t"] == last)
    points = [[forecast["start"] + i * STEP, v] for i, v in enumerate(forecast["values"])]
    estimate = {
        "solar_profile": {
            q: 280.0 * math.sin(math.pi * (q / 4 - 7) / 12) if 28 <= q < 76 else 0.0
            for q in range(96)
        },
        "solar_day_wh": 1800,
        "solar_days": 3,
        "load_w": 110.0,
        "charge_w": 1500.0,
    }
    plan = build_adaptive_plan(
        [(datetime.fromtimestamp(t, UTC), v) for t, v in points],
        datetime.fromtimestamp(now, UTC),
        round(battery),
        estimate,
    )
    store.put_state(
        "plan",
        {**plan, "forecast": points, "forecast_at": last, "index_now": 70},
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

    def mix(self, day: object, now: datetime) -> list:
        return []

    def prices(self, since: object, now: datetime) -> list:
        return []

    def jackery(self, now: object) -> None:
        return None


app = create_app(Settings(role="web"), sample_store(int(time.time())), NoSources(), clock=time.time)
