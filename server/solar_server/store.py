"""Where readings live.

Firestore holds one document per Pacific day per series, with the day's
points in an `items` array, so a 48-hour view is a handful of document reads
(well inside the free tier). `state/*` documents hold the latest plan and the
plug's latest report.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from planner.plan import PACIFIC

SAMPLES = "samples"  # every 5 min: battery, solar, emissions
PLUG = "plug"  # every minute: relay state, reason, grid watts


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
    def day(self, series: str, day: str) -> list[dict[str, Any]]: ...
    def put_state(self, name: str, data: dict[str, Any]) -> None: ...
    def get_state(self, name: str) -> dict[str, Any] | None: ...


def window(store: Store, series: str, since: int, until: int) -> list[dict[str, Any]]:
    items = [i for d in day_keys(since, until) for i in store.day(series, d)]
    return sorted((i for i in items if since <= i["t"] <= until), key=lambda i: i["t"])


class MemoryStore:
    """For tests and running locally without Google credentials."""

    def __init__(self) -> None:
        self.series: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.state: dict[str, dict] = {}

    def append(self, series: str, item: dict[str, Any]) -> None:
        self.series[(series, day_key(item["t"]))].append(dict(item))

    def day(self, series: str, day: str) -> list[dict[str, Any]]:
        return list(self.series.get((series, day), []))

    def put_state(self, name: str, data: dict[str, Any]) -> None:
        self.state[name] = dict(data)

    def get_state(self, name: str) -> dict[str, Any] | None:
        return self.state.get(name)


class FirestoreStore:
    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore

        self._fs = firestore
        self.db = firestore.Client(project=project or None)

    def append(self, series: str, item: dict[str, Any]) -> None:
        ref = self.db.collection(series).document(day_key(item["t"]))
        ref.set({"items": self._fs.ArrayUnion([item])}, merge=True)

    def day(self, series: str, day: str) -> list[dict[str, Any]]:
        snap = self.db.collection(series).document(day).get()
        return list((snap.to_dict() or {}).get("items", [])) if snap.exists else []

    def put_state(self, name: str, data: dict[str, Any]) -> None:
        self.db.collection("state").document(name).set(_state_document(data))

    def get_state(self, name: str) -> dict[str, Any] | None:
        snap = self.db.collection("state").document(name).get()
        return _state_data(snap.to_dict() or {}) if snap.exists else None
