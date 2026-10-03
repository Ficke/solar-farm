"""A local server with a day of made-up readings, for working on the dashboard.

uv run uvicorn solar_server.dev:app --port 8000
"""

from __future__ import annotations

import math
import time

from solar_server.app import create_app
from solar_server.config import Settings
from solar_server.store import PLUG, SAMPLES, MemoryStore


def sample_store(now: int) -> MemoryStore:
    store = MemoryStore()
    start = now - now % 300 - 3 * 86400
    battery = 70.0
    windows = []
    for t in range(start, now + 1, 300):
        hour = (t // 3600 - 7) % 24  # roughly Pacific
        solar = max(0.0, 230 * math.sin(math.pi * (hour - 7) / 12)) if 7 <= hour < 19 else 0.0
        moer = 900 - 450 * max(0.0, math.sin(math.pi * (hour - 8) / 10)) if 8 <= hour < 18 else 900
        on = 11 <= hour < 13
        grid = 300.0 if on and battery < 80 else 0.0
        battery = min(100.0, max(5.0, battery + (solar + grid - 60) * 5 / 60 / 30.72))
        store.append(
            SAMPLES,
            {
                "t": t,
                "battery_pct": round(battery),
                "solar_w": round(solar),
                "moer": moer,
                "index": round(moer / 10),
            },
        )
        if on and t % 3600 == 0 and hour == 11:
            windows.append([t, t + 7200])
    for t in range(start, now + 1, 60):
        hour = (t // 3600 - 7) % 24
        on = 11 <= hour < 13
        store.append(
            PLUG,
            {
                "t": t,
                "on": on,
                "reason": "peak" if 16 <= hour < 21 else "plan",
                "w": 280.0 if on else 0.0,
            },
        )
    future = now - now % 300
    forecast = [
        [
            future + i * 300,
            900
            - 450 * max(0.0, math.sin(math.pi * (((future + i * 300) // 3600 - 7) % 24 - 8) / 10)),
        ]
        for i in range(288)
    ]
    nxt = now - now % 86400 + 86400 + 18 * 3600
    store.put_state(
        "plan",
        {
            "generated_at": now - 600,
            "windows": [*windows[-1:], [nxt, nxt + 7200]],
            "forecast": forecast,
        },
    )
    return store


class NoSources:
    """The web role never calls out; these only exist to satisfy create_app."""

    def forecast(self, hours: int) -> list:
        return []

    def signal_index(self) -> float:
        return 0.0

    def jackery(self, now: object) -> None:
        return None


app = create_app(Settings(role="web"), sample_store(int(time.time())), NoSources(), clock=time.time)
