"""Read CAISO-wide generation in MW and NP15/SP15 hub prices in $/MWh.

Both use five-minute intervals. Imports are negative during exports;
batteries are negative while charging. Prices come from OASIS.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, date, datetime, time, timedelta

import requests

from planner.plan import PACIFIC

URL = "https://www.caiso.com/outlook"

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
    """Parse fuel rows in MW with ``t`` in Unix seconds."""
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


OASIS = "https://oasis.caiso.com/oasisapi/SingleZip"
HUBS = {"TH_NP15_GEN-APND": "np15", "TH_SP15_GEN-APND": "sp15"}


def fetch_prices(start: datetime, end: datetime, session: requests.Session | None = None) -> str:
    """OASIS answers with a zip holding one CSV, or an XML error when it's busy."""
    s = session or requests.Session()
    fmt = "%Y%m%dT%H:%M-0000"
    r = s.get(
        OASIS,
        params={
            "queryname": "PRC_INTVL_LMP",
            "market_run_id": "RTM",
            "version": "1",
            "node": ",".join(HUBS),
            "startdatetime": start.astimezone(UTC).strftime(fmt),
            "enddatetime": end.astimezone(UTC).strftime(fmt),
            "resultformat": "6",
        },
        timeout=30,
    )
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        if not name.endswith(".csv"):
            raise ValueError(f"OASIS error: {z.read(name)[:300]!r}")
        return z.read(name).decode()


def parse_prices(text: str) -> list[dict]:
    """Parse NP15/SP15 prices in $/MWh with Unix-second interval starts."""
    by_t: dict[int, dict] = {}
    for row in csv.DictReader(io.StringIO(text.lstrip("\N{ZERO WIDTH NO-BREAK SPACE}"))):
        key = HUBS.get(row.get("NODE", ""))
        if key is None or row.get("LMP_TYPE") != "LMP":
            continue
        try:
            t = int(datetime.fromisoformat(row["INTERVALSTARTTIME_GMT"]).timestamp())
            v = round(float(row["MW"]), 2)
        except KeyError, ValueError:
            continue
        by_t.setdefault(t, {"t": t, "np15": None, "sp15": None})[key] = v
    return [by_t[t] for t in sorted(by_t)]


def prices(since: datetime, now: datetime, session: requests.Session | None = None) -> list[dict]:
    end = now + timedelta(minutes=5)
    return parse_prices(fetch_prices(since, end, session))
