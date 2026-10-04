"""What the API returns. The dashboard's TypeScript types are generated from these.

After changing a model, run `just api` to update web/openapi.json; the
dashboard's types follow from it on its next check or build.
"""

from __future__ import annotations

from pydantic import BaseModel

type Window = tuple[int, int]  # [start, end), unix seconds


class Sample(BaseModel):
    """Every 5 minutes: the Jackery and WattTime."""

    t: int
    battery_pct: float | None = None
    solar_w: float | None = None
    ac_input_w: float | None = None
    output_w: float | None = None
    moer: float | None = None  # WattTime's actual marginal CO2, lb/MWh
    moer_t: int | None = None
    index: float | None = None  # 0-100 percentile of the past month, lower is cleaner


class PlugReport(BaseModel):
    """Every minute, from the plug."""

    t: int
    on: bool
    reason: str
    w: float | None = None
    wh: float | None = None
    index: float | None = None
    plan_at: int | None = None


class StoredPlugReport(PlugReport):
    received: int | None = None


class MixRow(BaseModel):
    """CAISO generation by fuel, MW. Batteries are negative while charging."""

    t: int
    solar: float | None = None
    wind: float | None = None
    geothermal: float | None = None
    biomass: float | None = None
    biogas: float | None = None
    small_hydro: float | None = None
    coal: float | None = None
    nuclear: float | None = None
    gas: float | None = None
    large_hydro: float | None = None
    batteries: float | None = None
    imports: float | None = None
    other: float | None = None


class Today(BaseModel):
    solar_wh: int
    grid_wh: int


class PlanSummary(BaseModel):
    generated_at: int
    windows: list[Window]
    index_now: float | None = None


class Now(BaseModel):
    now: int
    sample: Sample | None
    plug: StoredPlugReport | None
    today: Today
    plan: PlanSummary | None


class Timeline(BaseModel):
    now: int
    since: int
    samples: list[Sample]
    plug: list[StoredPlugReport]
    forecast: list[tuple[int, float]]  # [t, lb/MWh]
    mix: list[MixRow]
    windows: list[Window]


class Accuracy(BaseModel):
    lead_hours: int
    points: list[tuple[int, float, float | None]]  # [t, actual, forecast made lead_hours earlier]
    error: int | None
    compared: int


class Day(BaseModel):
    day: str
    solar_wh: int
    grid_wh: int
    battery_peak_pct: float | None


class Reserve(BaseModel):
    reserve_pct: int | None
    good_day_wh: int | None = None
    days: int


class Daily(BaseModel):
    days: list[Day]
    reserve: Reserve
