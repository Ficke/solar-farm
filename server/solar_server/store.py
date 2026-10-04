"""Store each series in daily Pacific documents with an ``items`` array.

Live views read ``state/*`` snapshots; longer summaries read ``totals/<day>``
instead of raw history. State uses JSON to preserve nested arrays.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from planner.plan import PACIFIC

SAMPLES = "samples"
PLUG = "plug"
PLANS = "plans"
FORECASTS = "forecasts"
MIX = "mix"
TOTALS = "totals"
LOCKS = "locks"


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
    def claim(self, name: str, now: int, ttl: int) -> bool: ...
    def release(self, name: str) -> None: ...


def window(store: Store, series: str, since: int, until: int) -> list[dict[str, Any]]:
    items = [i for d in day_keys(since, until) for i in store.day(series, d)]
    return sorted((i for i in items if since <= i["t"] <= until), key=lambda i: i["t"])


class MemoryStore:
    """Store data in memory for tests and local development."""

    def __init__(self) -> None:
        self.series: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.state: dict[str, dict] = {}
        self.days: dict[str, dict] = {}
        self.locks: dict[str, int] = {}

    def append(self, series: str, item: dict[str, Any]) -> None:
        self.series[(series, day_key(item["t"]))].append(dict(item))

    def extend(self, series: str, items: list[dict[str, Any]]) -> None:
        # Match Firestore ArrayUnion deduplication.
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

    def claim(self, name: str, now: int, ttl: int) -> bool:
        if self.locks.get(name, 0) > now:
            return False
        self.locks[name] = now + ttl
        return True

    def release(self, name: str) -> None:
        self.locks.pop(name, None)


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
        refs = [self.db.collection(TOTALS).document(d) for d in days]
        snaps = {s.id: s for s in self.db.get_all(refs) if s.exists}
        return [snaps[d].to_dict() or {} for d in days if d in snaps]

    def claim(self, name: str, now: int, ttl: int) -> bool:
        """Atomically claim an expired or missing lease for ``ttl`` seconds."""
        ref = self.db.collection(LOCKS).document(name)

        @self._fs.transactional
        def take(transaction) -> bool:
            snap = ref.get(transaction=transaction)
            if snap.exists and (snap.to_dict() or {}).get("until", 0) > now:
                return False
            transaction.set(ref, {"until": now + ttl})
            return True

        return take(self.db.transaction())

    def release(self, name: str) -> None:
        self.db.collection(LOCKS).document(name).set({"until": 0})
