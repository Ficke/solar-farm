"""Fetch WattTime v3 forecasts, actuals and signal indices."""

from __future__ import annotations

from datetime import datetime, timedelta

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
    signal_type: str = "co2_moer",
) -> list[tuple[datetime, float]]:
    """Return five-minute (UTC time, value) pairs; MOER is measured in lb/MWh."""
    s = session or requests.Session()
    r = s.get(
        f"{API}/v3/forecast",
        params={"region": region, "signal_type": signal_type, "horizon_hours": horizon_hours},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return parse_forecast(r.json())


def historical(
    token: str,
    start: datetime,
    end: datetime,
    region: str = "CAISO_NORTH",
    signal_type: str = "co2_moer",
    session: requests.Session | None = None,
) -> list[tuple[datetime, float]]:
    """Return historical five-minute (UTC time, value) pairs."""
    s = session or requests.Session()
    r = s.get(
        f"{API}/v3/historical",
        params={
            "region": region,
            "signal_type": signal_type,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return parse_forecast(r.json())


def latest(
    token: str, now: datetime, region: str = "CAISO_NORTH", signal_type: str = "co2_moer"
) -> tuple[datetime, float] | None:
    """Return the latest actual from the last 30 minutes, or None if unavailable."""
    points = historical(token, now - timedelta(minutes=30), now, region, signal_type)
    return max(points) if points else None


def signal_index(
    token: str, region: str = "CAISO_NORTH", session: requests.Session | None = None
) -> float:
    """Return the current 0-100 cleanliness percentile used by the plug fallback."""
    s = session or requests.Session()
    r = s.get(
        f"{API}/v3/signal-index",
        params={"region": region, "signal_type": "co2_moer"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    r.raise_for_status()
    return parse_signal_index(r.json())


def parse_signal_index(body: dict) -> float:
    return float(body["data"][0]["value"])


def parse_forecast(body: dict) -> list[tuple[datetime, float]]:
    points = []
    for p in body.get("data", []):
        t = datetime.fromisoformat(p["point_time"].replace("Z", "+00:00"))
        points.append((t, float(p["value"])))
    return points
