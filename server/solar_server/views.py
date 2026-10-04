"""Shapes the dashboard reads. Pure functions over stored points."""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise

from planner import telemetry
from solar_server.store import FORECASTS, MIX, PLUG, SAMPLES, Store, day_key, window

MAX_GAP = 3600  # don't integrate across outages longer than an hour


def integrate_wh(points: list[tuple[int, float]]) -> float:
    wh = 0.0
    for (t0, w0), (t1, w1) in pairwise(points):
        wh += (w0 + w1) / 2 * min(t1 - t0, MAX_GAP) / 3600
    return wh


def _series(items: list[dict], key: str) -> list[tuple[int, float]]:
    return [(i["t"], float(i[key])) for i in items if i.get(key) is not None]


def now_view(store: Store, now: int) -> dict:
    samples = window(store, SAMPLES, now - 2 * 3600, now)
    reports = window(store, PLUG, now - 3600, now)
    today = day_key(now)
    today_samples = [
        s for s in window(store, SAMPLES, now - 86400, now) if day_key(s["t"]) == today
    ]
    today_plug = [r for r in window(store, PLUG, now - 86400, now) if day_key(r["t"]) == today]
    plan = store.get_state("plan") or {}
    return {
        "now": now,
        "sample": samples[-1] if samples else None,
        "plug": reports[-1] if reports else None,
        "today": {
            "solar_wh": round(integrate_wh(_series(today_samples, "solar_w"))),
            "grid_wh": round(integrate_wh(_series(today_plug, "w"))),
        },
        "plan": {k: plan.get(k) for k in ("generated_at", "windows", "index_now")}
        if plan
        else None,
    }


def timeline_view(store: Store, now: int, past_hours: int = 24) -> dict:
    since = now - past_hours * 3600
    plan = store.get_state("plan") or {}
    return {
        "now": now,
        "since": since,
        "samples": window(store, SAMPLES, since, now),
        "plug": [
            {k: r.get(k) for k in ("t", "on", "reason", "w")}
            for r in window(store, PLUG, since, now)
        ],
        "forecast": [p for p in plan.get("forecast", []) if p[0] >= now - 300],
        # CAISO sometimes revises a row; the latest stored copy wins.
        "mix": list({i["t"]: i for i in window(store, MIX, since, now)}.values()),
        "windows": plan.get("windows", []),
    }


def daily_view(store: Store, now: int, days: int = 14) -> dict:
    since = now - days * 86400
    by_day_solar: dict[str, list] = defaultdict(list)
    by_day_grid: dict[str, list] = defaultdict(list)
    peak: dict[str, float] = {}
    for s in window(store, SAMPLES, since, now):
        d = day_key(s["t"])
        if s.get("solar_w") is not None:
            by_day_solar[d].append((s["t"], float(s["solar_w"])))
        if s.get("battery_pct") is not None:
            peak[d] = max(peak.get(d, 0.0), float(s["battery_pct"]))
    for r in window(store, PLUG, since, now):
        if r.get("w") is not None:
            by_day_grid[day_key(r["t"])].append((r["t"], float(r["w"])))
    keys = sorted(set(by_day_solar) | set(by_day_grid))
    rows = [
        {
            "day": d,
            "solar_wh": round(integrate_wh(by_day_solar[d])),
            "grid_wh": round(integrate_wh(by_day_grid[d])),
            "battery_peak_pct": peak.get(d),
        }
        for d in keys
    ]
    # Same rule as the weekly GitHub issue; only full days count.
    full = {d: integrate_wh(by_day_solar[d]) for d in keys if len(by_day_solar[d]) >= 36}
    full.pop(day_key(now), None)
    return {"days": rows, "reserve": telemetry.recommend_reserve(full)}


def accuracy_view(store: Store, now: int, lead_hours: int = 6, past_hours: int = 24) -> dict:
    """WattTime's forecast made ``lead_hours`` ahead next to what actually happened.

    For each actual reading, the forecast is the latest one made at least
    ``lead_hours`` before it. ``error`` is the mean absolute difference.
    """
    since = now - past_hours * 3600
    lead = lead_hours * 3600
    snapshots = window(store, FORECASTS, since - lead - 86400, now)
    points: list[list[float | int | None]] = []
    errors: list[float] = []
    for s in window(store, SAMPLES, since, now):
        if s.get("moer") is None:
            continue
        t = s.get("moer_t", s["t"])
        predicted = None
        for f in reversed(snapshots):
            if f["t"] > t - lead:
                continue
            i = (t - f["start"]) // f["step"]
            if 0 <= i < len(f["values"]):
                predicted = f["values"][i]
            break
        points.append([t, s["moer"], predicted])
        if predicted is not None:
            errors.append(abs(s["moer"] - predicted))
    return {
        "lead_hours": lead_hours,
        "points": points,
        "error": round(sum(errors) / len(errors)) if errors else None,
        "compared": len(errors),
    }
