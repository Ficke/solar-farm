"""Read Jackery telemetry through the unofficial socketry API.

Use a shared second account: Jackery permits one login per account, so using
the phone app's account can log it out. The server tolerates telemetry failures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

# Read-only Jackery app statistics endpoints, probed to find finer energy data
# than the property map, whose power fields refresh once every 5 minutes.
# "id" sends deviceId, "sn" sends deviceSn; "day" adds a one-day date range.
STAT_QUERIES = (
    ("/v1/device/stat/deviceStatistic", "id", False),
    ("/v1/device/stat/today", "sn", False),
    ("/v1/device/stat/battery", "id", True),
    ("/v1/device/stat/pv", "id", True),
    ("/v1/device/stat/onGrid", "id", True),
    ("/v1/device/stat/eps", "id", True),
    ("/v1/device/stat/soc", "id", True),
    ("/v1/device/stat/ct/statics", "id", True),
    ("/v1/device/chargeReport", "sn", False),
)
STAT_LIMIT = 60_000  # Characters kept per response, to fit one Firestore document.
PUSH_LIMIT = 500  # MQTT messages kept per listen.


@dataclass
class Reading:
    time: datetime
    battery_pct: float | None
    input_w: float | None
    ac_input_w: float | None
    car_input_w: float | None
    output_w: float | None
    raw: dict

    @property
    def solar_w(self) -> float | None:
        """Infer solar watts by subtracting AC and car input from total input."""
        if self.input_w is None:
            return None
        other = (self.ac_input_w or 0) + (self.car_input_w or 0)
        return max(0.0, self.input_w - other)


def parse_properties(props: dict, now: datetime) -> Reading:
    props = props.get("properties", props)

    def num(key: str) -> float | None:
        v = props.get(key)
        try:
            return float(v) if v is not None else None
        except TypeError, ValueError:
            return None

    return Reading(
        time=now,
        battery_pct=num("rb"),
        input_w=num("ip"),
        ac_input_w=num("acip"),
        car_input_w=num("cip"),
        output_w=num("op"),
        raw=props,
    )


class Account:
    """Reuse a device session; retry login after a property-read failure."""

    def __init__(self, email: str, password: str, serial: str | None) -> None:
        self.email, self.password, self.serial = email, password, serial
        self._client = None
        self._device = None

    async def _connect(self):
        from socketry import Client

        if self._device is None:
            self._client = await Client.login(self.email, self.password)
            devices = await self._client.fetch_devices()
            index = 0
            if self.serial:
                index = next(i for i, d in enumerate(devices) if str(d.get("devSn")) == self.serial)
            self._device = self._client.device(index)
        return self._device

    async def read(self, now: datetime) -> Reading:
        device = await self._connect()
        try:
            props = await device.get_all_properties()
        except Exception:
            self._device = None
            raise
        return parse_properties(props, now)

    async def stats(self, day: date) -> dict[str, dict]:
        """Fetch each statistics endpoint for ``day``; record errors per endpoint."""
        import aiohttp
        from socketry._constants import API_BASE, APP_HEADERS

        device = await self._connect()
        assert self._client is not None
        headers = {**APP_HEADERS, "token": self._client.token}
        out: dict[str, dict] = {}
        async with aiohttp.ClientSession() as session:
            for path, key, dated in STAT_QUERIES:
                params = {"deviceId": device.device_id} if key == "id" else {"deviceSn": device.sn}
                if dated:
                    params |= {"dateType": "day", "beginDate": str(day), "endDate": str(day)}
                try:
                    async with session.get(
                        API_BASE + path.removeprefix("/v1"),
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        text = await resp.text()
                        out[path] = {"status": resp.status, "body": text[:STAT_LIMIT]}
                except Exception as e:
                    out[path] = {"error": repr(e)[:500]}
        return out

    async def listen(self, seconds: float) -> list[dict]:
        """Record the MQTT property pushes for this device over ``seconds``; read-only."""
        import asyncio
        import time

        device = await self._connect()
        assert self._client is not None
        messages: list[dict] = []

        async def on_push(sn: str, props: dict) -> None:
            if sn == device.sn and len(messages) < PUSH_LIMIT:
                messages.append({"t": round(time.time(), 1), **scalars(props)})

        subscription = await self._client.subscribe(on_push)
        try:
            await asyncio.sleep(seconds)
        finally:
            await subscription.stop()
        return messages


def scalars(props: dict) -> dict:
    """Keep the JSON scalar fields of a property map, which Firestore can store."""
    props = props.get("properties", props)
    return {k: v for k, v in props.items() if isinstance(v, (int, float, str, bool)) or v is None}


def stat_summary(responses: dict[str, dict]) -> dict[str, str]:
    """Return each endpoint's result code and message, for logs."""
    out = {}
    for path, r in responses.items():
        try:
            body = json.loads(r.get("body", ""))
            out[path] = f"{body.get('code')} {body.get('msg', '')}".strip()
        except ValueError:
            out[path] = str(r.get("status") or r.get("error"))
    return out
