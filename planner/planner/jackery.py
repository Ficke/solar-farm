"""Read Jackery telemetry through the unofficial socketry API.

Use a shared second account: Jackery permits one login per account, so using
the phone app's account can log it out. The server tolerates telemetry failures.
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
