"""Read-only Jackery telemetry through Jackery's (unofficial) cloud API.

Uses the reverse-engineered `socketry` library. Jackery allows one login per
account at a time, so use a second Jackery account that the power station is
shared with; otherwise the phone app keeps getting logged out.

This only ever reads properties. If Jackery changes its protocol this module
fails, and the planner carries on without telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
        """Total input minus AC and car input; what the panel is delivering."""
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
    """Reads one power station, logging in once rather than for every reading.

    socketry renews the token when it nears expiry. After any failure the next
    read logs in again.
    """

    def __init__(self, email: str, password: str, serial: str | None) -> None:
        self.email, self.password, self.serial = email, password, serial
        self._device = None

    async def read(self, now: datetime) -> Reading:
        from socketry import Client

        if self._device is None:
            client = await Client.login(self.email, self.password)
            devices = await client.fetch_devices()
            index = 0
            if self.serial:
                index = next(i for i, d in enumerate(devices) if str(d.get("devSn")) == self.serial)
            self._device = client.device(index)
        try:
            props = await self._device.get_all_properties()
        except Exception:
            self._device = None
            raise
        return parse_properties(props, now)
