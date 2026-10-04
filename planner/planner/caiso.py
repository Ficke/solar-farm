"""CAISO's grid mix: megawatts by fuel, every 5 minutes, for all of CAISO.

CAISO publishes one CSV per Pacific day, no key needed. Imports aren't split
by fuel; batteries are negative while charging.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time

import requests

from planner.plan import PACIFIC

URL = "https://www.caiso.com/outlook"

# CSV header -> stored key
COLUMNS = {
    "Solar": "solar",
    "Wind": "wind",
    "Geothermal": "geothermal",
    "Biomass": "biomass",
    "Biogas": "biogas",
    "Small hydro": "small_hydro",
    "Coal": "coal",
    "Nuclear": "nuclear",
    "Natural Gas": "gas",
    "Large Hydro": "large_hydro",
    "Batteries": "batteries",
    "Imports": "imports",
    "Other": "other",
}


def fetch(day: date, today: date, session: requests.Session | None = None) -> str:
    s = session or requests.Session()
    path = "current" if day == today else f"history/{day:%Y%m%d}"
    r = s.get(f"{URL}/{path}/fuelsource.csv", timeout=20)
    r.raise_for_status()
    return r.text


def parse(text: str, day: date) -> list[dict]:
    """Rows as {t, solar, wind, ...} in MW; t is Unix seconds."""
    rows = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        try:
            hh, mm = (int(x) for x in row["Time"].split(":"))
            t = datetime.combine(day, time(hh % 24, mm), PACIFIC)
            item: dict = {"t": int(t.timestamp())}
            for col, key in COLUMNS.items():
                v = (row.get(col) or "").strip()
                item[key] = round(float(v)) if v else None
        except KeyError, ValueError:
            continue
        rows.append(item)
    return rows


def mix(day: date, now: datetime, session: requests.Session | None = None) -> list[dict]:
    today = now.astimezone(PACIFIC).date()
    return parse(fetch(day, today, session), day)
