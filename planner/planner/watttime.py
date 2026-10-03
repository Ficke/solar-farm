"""Minimal WattTime v3 client: login and marginal-emissions forecast."""

from __future__ import annotations

from datetime import datetime

import requests

API = "https://api.watttime.org"


def login(user: str, password: str, session: requests.Session | None = None) -> str:
    s = session or requests.Session()
    r = s.get(f"{API}/login", auth=(user, password), timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def forecast(
    token: str,
    region: str = "CAISO_NORTH",
    horizon_hours: int = 24,
    session: requests.Session | None = None,
) -> list[tuple[datetime, float]]:
    """Return (point_time UTC, MOER lbs/MWh) pairs, 5 minutes apart."""
    s = session or requests.Session()
    r = s.get(
        f"{API}/v3/forecast",
        params={"region": region, "signal_type": "co2_moer", "horizon_hours": horizon_hours},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return parse_forecast(r.json())


def parse_forecast(body: dict) -> list[tuple[datetime, float]]:
    points = []
    for p in body.get("data", []):
        t = datetime.fromisoformat(p["point_time"].replace("Z", "+00:00"))
        points.append((t, float(p["value"])))
    return points
