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


async def read(email: str, password: str, serial: str | None, now: datetime) -> Reading:
    from socketry import Client

    client = await Client.login(email, password)
    devices = await client.fetch_devices()
    index = 0
    if serial:
        index = next(i for i, d in enumerate(devices) if str(d.get("devSn")) == serial)
    props = await client.device(index).get_all_properties()
    return parse_properties(props, now)
