"""Fetch from WattTime, CAISO and Jackery. Kept thin so tests can swap in fakes."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from planner.jackery import Account, Reading

from planner import caiso, watttime
from solar_server.config import Settings


class Sources(Protocol):
    def forecast(self, hours: int, signal: str = "co2_moer") -> list[tuple[datetime, float]]: ...
    def signal_index(self) -> float: ...
    def actual(self, signal: str, now: datetime) -> tuple[datetime, float] | None: ...
    def mix(self, day: date, now: datetime) -> list[dict]: ...
    def jackery(self, now: datetime) -> Reading | None: ...


@dataclass
class LiveSources:
    settings: Settings
    _token: str = ""
    _token_at: float = 0.0
    _jackery: Account | None = None

    def _auth(self) -> str:
        # WattTime tokens last 30 minutes; reuse one while the instance is warm.
        if not self._token or time.monotonic() - self._token_at > 25 * 60:
            s = self.settings
            self._token = watttime.login(s.watttime_username, s.watttime_password)
            self._token_at = time.monotonic()
        return self._token

    def forecast(self, hours: int, signal: str = "co2_moer") -> list[tuple[datetime, float]]:
        return watttime.forecast(
            self._auth(), self.settings.region, horizon_hours=hours, signal_type=signal
        )

    def signal_index(self) -> float:
        return watttime.signal_index(self._auth(), self.settings.region)

    def actual(self, signal: str, now: datetime) -> tuple[datetime, float] | None:
        return watttime.latest(self._auth(), now, self.settings.region, signal)

    def mix(self, day: date, now: datetime) -> list[dict]:
        return caiso.mix(day, now)

    def jackery(self, now: datetime) -> Reading | None:
        s = self.settings
        if not s.jackery_email:
            return None
        # Readings come every minute; keep the login while the instance is warm.
        if self._jackery is None:
            self._jackery = Account(s.jackery_email, s.jackery_password, s.jackery_sn or None)
        return asyncio.run(self._jackery.read(now))
