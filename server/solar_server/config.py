"""Settings come from the environment Cloud Run is given (see infra/run.tf)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    role: str = "web"
    project: str = ""
    region: str = "CAISO_NORTH"
    budget_hours: float = 4.0
    plug_key: str = field(default="", repr=False)
    scheduler_sa: str = ""
    watttime_username: str = field(default="", repr=False)
    watttime_password: str = field(default="", repr=False)
    jackery_email: str = field(default="", repr=False)
    jackery_password: str = field(default="", repr=False)
    jackery_sn: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ.get
        return cls(
            role=e("SOLAR_ROLE", "web"),
            project=e("GOOGLE_CLOUD_PROJECT", ""),
            region=e("WATTTIME_REGION", "CAISO_NORTH"),
            budget_hours=float(e("BUDGET_HOURS", "4")),
            plug_key=e("PLUG_KEY", ""),
            scheduler_sa=e("SCHEDULER_SERVICE_ACCOUNT", ""),
            watttime_username=e("WATTTIME_USERNAME", ""),
            watttime_password=e("WATTTIME_PASSWORD", ""),
            jackery_email=e("JACKERY_EMAIL", ""),
            jackery_password=e("JACKERY_PASSWORD", ""),
            jackery_sn=e("JACKERY_SN", ""),
        )
