"""Define dashboard API models and generated TypeScript contracts.

Run ``just api`` after model changes, then regenerate types with the web check or build.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

type Window = tuple[int, int]  # Endpoints use half-open Unix seconds.


class Sample(BaseModel):
    """Record available Jackery telemetry and new WattTime readings."""

    t: int
    battery_pct: float | None = None
    solar_w: float | None = None
    ac_input_w: float | None = None
    output_w: float | None = None
    runtime_h: float | None = None  # Jackery's estimate of hours left at the current draw.
    full_h: float | None = None  # Jackery's estimate of hours to full while charging.
    moer: float | None = None  # WattTime reports marginal CO2 in lb/MWh.
    moer_t: int | None = None
    index: float | None = None  # Lower percentiles indicate cleaner grid power.


class PlugReport(BaseModel):
    """Record the plug's minute status."""

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
    """Record CAISO generation in MW; batteries are negative while charging."""

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


class PriceRow(BaseModel):
    """Real-time price at CAISO's north and south trading hubs, $/MWh."""

    t: int
    np15: float | None = None
    sp15: float | None = None


class Today(BaseModel):
    solar_wh: int
    grid_wh: int


class PlanBlock(BaseModel):
    """One 15-minute block of the plan, clipped to now and the deadline."""

    s: int
    e: int
    mode: Literal["charge", "bypass", "solar", "battery", "peak", "none"]
    moer: float | None  # forecast marginal CO2, lb/MWh
    pct: float  # projected battery % at the block's end
    recharge: float | None  # lb/MWh of the block that would refill the battery


class PlanSummary(BaseModel):
    generated_at: int
    windows: list[Window]
    index_now: float | None = None
    strategy: Literal["adaptive", "fallback"] | None = None
    target_pct: float | None = None
    deadline: int | None = None
    floor_pct: float | None = None
    solar_day_wh: int | None = None
    solar_days: int | None = None
    charge_w: float | None = None
    grid_wh: int | None = None
    blocks: list[PlanBlock] = []
    shortfall_wh: int | None = None
    forecast_at: int | None = None
    forecast_until: int | None = None
    missing: list[Literal["battery", "forecast", "forecast_horizon"]] = []
    zeros_doubted_since: int | None = None


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
    load: list[tuple[int, float]]  # Pairs contain Unix seconds and W.
    forecast: list[tuple[int, float]]  # Pairs contain Unix seconds and lb/MWh.
    mix: list[MixRow]
    prices: list[PriceRow]


class Accuracy(BaseModel):
    lead_hours: int
    points: list[tuple[int, float, float | None]]  # Each point holds time, actual and forecast.
    error: int | None
    compared: int


class Day(BaseModel):
    day: str
    solar_wh: int
    grid_wh: int
    load_wh: int
    battery_peak_pct: float | None


class Reserve(BaseModel):
    reserve_pct: int | None
    good_day_wh: int | None = None
    days: int


class Daily(BaseModel):
    days: list[Day]
    reserve: Reserve


class Co2Period(BaseModel):
    """Summarize a Pacific day, Monday-based week or month."""

    start: str
    load_wh: int
    grid_wh: int
    solar_wh: int
    load_lb: float  # Model direct-grid load emissions.
    grid_lb: float  # Attribute grid emissions to charging time.
    used_lb: float  # Attribute stored grid emissions to load time.
    avoided_lb: float  # Subtract used_lb from the direct-grid baseline.


class Co2(BaseModel):
    by: Literal["day", "week", "month"]
    periods: list[Co2Period]
