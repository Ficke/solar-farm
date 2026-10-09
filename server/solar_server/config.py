"""Settings come from the environment Cloud Run is given (see infra/run.tf)."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    role: str = "web"
    project: str = ""
    region: str = "CAISO_NORTH"
    budget_hours: float = 1.0  # fallback only, without battery telemetry
    solar_day_wh: float = 500.0
    charge_w: float = 1700.0
    floor_pct: float = 20.0
    plug_key: str = field(default="", repr=False)
    scheduler_sa: str = ""
    watttime_username: str = field(default="", repr=False)
    watttime_password: str = field(default="", repr=False)
    jackery_email: str = field(default="", repr=False)
    jackery_password: str = field(default="", repr=False)
    jackery_sn: str = ""

    def __post_init__(self) -> None:
        values = (self.budget_hours, self.solar_day_wh, self.charge_w, self.floor_pct)
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError("charging settings must be finite and nonnegative")
        if self.charge_w == 0 or self.floor_pct > 80:
            raise ValueError("CHARGE_W must be positive; BATTERY_FLOOR_PCT must be at most 80")

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ.get
        return cls(
            role=e("SOLAR_ROLE", "web"),
            project=e("GOOGLE_CLOUD_PROJECT", ""),
            region=e("WATTTIME_REGION", "CAISO_NORTH"),
            budget_hours=float(e("BUDGET_HOURS", "1")),
            solar_day_wh=float(e("SOLAR_DAY_WH", "500")),
            charge_w=float(e("CHARGE_W", "1700")),
            floor_pct=float(e("BATTERY_FLOOR_PCT", "20")),
            plug_key=e("PLUG_KEY", ""),
            scheduler_sa=e("SCHEDULER_SERVICE_ACCOUNT", ""),
            watttime_username=e("WATTTIME_USERNAME", ""),
            watttime_password=e("WATTTIME_PASSWORD", ""),
            jackery_email=e("JACKERY_EMAIL", ""),
            jackery_password=e("JACKERY_PASSWORD", ""),
            jackery_sn=e("JACKERY_SN", ""),
        )
