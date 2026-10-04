"""Where readings live.

Firestore holds one document per Pacific day per series, with the day's
points in an `items` array, so a 48-hour view is a handful of document reads
(well inside the free tier). `state/*` documents hold the latest plan, sample
and plug report, with today's running totals, so the dashboard's live view
reads three small documents instead of whole days. `totals/<day>` holds
each day's energy and CO2, so longer ranges sum small documents.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from planner.plan import PACIFIC

SAMPLES = "samples"  # every minute: battery, solar; emissions every 5 min
PLUG = "plug"  # every minute: relay state, reason, grid watts
PLANS = "plans"  # each replan that changed the windows, plus forecast updates
FORECASTS = "forecasts"  # every 30 min: the 24-hour forecast each plan used
MIX = "mix"  # every 5 min: CAISO's generation by fuel, MW: {t, solar, wind, gas, ...}
TOTALS = "totals"  # one document per day: energy and CO2 totals (see totals.py)


def _state_document(data: dict[str, Any]) -> dict[str, str]:
    # Firestore rejects arrays nested directly inside arrays, which both plan
    # windows and forecast points use. JSON preserves the public data shape.
    return {"data_json": json.dumps(data, separators=(",", ":"))}


def _state_data(document: dict[str, Any]) -> dict[str, Any]:
    encoded = document.get("data_json")
    if isinstance(encoded, str):
        return json.loads(encoded)
    return document


def day_key(t: int) -> str:
    return datetime.fromtimestamp(t, UTC).astimezone(PACIFIC).date().isoformat()


def day_keys(since: int, until: int) -> list[str]:
    days = []
    d = datetime.fromtimestamp(since, UTC).astimezone(PACIFIC).date()
    end = datetime.fromtimestamp(until, UTC).astimezone(PACIFIC).date()
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


class Store(Protocol):
    def append(self, series: str, item: dict[str, Any]) -> None: ...
    def extend(self, series: str, items: list[dict[str, Any]]) -> None: ...
    def day(self, series: str, day: str) -> list[dict[str, Any]]: ...
    def put_state(self, name: str, data: dict[str, Any]) -> None: ...
    def get_state(self, name: str) -> dict[str, Any] | None: ...
    def put_total(self, day: str, data: dict[str, Any]) -> None: ...
    def totals(self, days: list[str]) -> list[dict[str, Any]]: ...


def window(store: Store, series: str, since: int, until: int) -> list[dict[str, Any]]:
    items = [i for d in day_keys(since, until) for i in store.day(series, d)]
    return sorted((i for i in items if since <= i["t"] <= until), key=lambda i: i["t"])


class MemoryStore:
    """For tests and running locally without Google credentials."""

    def __init__(self) -> None:
        self.series: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.state: dict[str, dict] = {}
        self.days: dict[str, dict] = {}

    def append(self, series: str, item: dict[str, Any]) -> None:
        self.series[(series, day_key(item["t"]))].append(dict(item))

    def extend(self, series: str, items: list[dict[str, Any]]) -> None:
        # Like Firestore's ArrayUnion: items already stored are skipped.
        for item in items:
            day = self.series[(series, day_key(item["t"]))]
            if item not in day:
                day.append(dict(item))

    def day(self, series: str, day: str) -> list[dict[str, Any]]:
        return list(self.series.get((series, day), []))

    def put_state(self, name: str, data: dict[str, Any]) -> None:
        self.state[name] = dict(data)

    def get_state(self, name: str) -> dict[str, Any] | None:
        return self.state.get(name)

    def put_total(self, day: str, data: dict[str, Any]) -> None:
        self.days[day] = dict(data)

    def totals(self, days: list[str]) -> list[dict[str, Any]]:
        return [dict(self.days[d]) for d in days if d in self.days]


class FirestoreStore:
    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore

        self._fs = firestore
        self.db = firestore.Client(project=project or None)

    def append(self, series: str, item: dict[str, Any]) -> None:
        ref = self.db.collection(series).document(day_key(item["t"]))
        ref.set({"items": self._fs.ArrayUnion([item])}, merge=True)

    def extend(self, series: str, items: list[dict[str, Any]]) -> None:
        # One write per day; ArrayUnion skips items already stored.
        by_day: dict[str, list] = defaultdict(list)
        for item in items:
            by_day[day_key(item["t"])].append(item)
        for day, chunk in by_day.items():
            ref = self.db.collection(series).document(day)
            ref.set({"items": self._fs.ArrayUnion(chunk)}, merge=True)

    def day(self, series: str, day: str) -> list[dict[str, Any]]:
        snap = self.db.collection(series).document(day).get()
        return list((snap.to_dict() or {}).get("items", [])) if snap.exists else []

    def put_state(self, name: str, data: dict[str, Any]) -> None:
        self.db.collection("state").document(name).set(_state_document(data))

    def get_state(self, name: str) -> dict[str, Any] | None:
        snap = self.db.collection("state").document(name).get()
        return _state_data(snap.to_dict() or {}) if snap.exists else None

    def put_total(self, day: str, data: dict[str, Any]) -> None:
        self.db.collection(TOTALS).document(day).set(data)

    def totals(self, days: list[str]) -> list[dict[str, Any]]:
        # One batched read; a year of days is 365 small documents.
        refs = [self.db.collection(TOTALS).document(d) for d in days]
        snaps = {s.id: s for s in self.db.get_all(refs) if s.exists}
        return [snaps[d].to_dict() or {} for d in days if d in snaps]
