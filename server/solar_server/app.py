"""HTTP routes. SOLAR_ROLE picks which half of the app a service exposes."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from solar_server import tasks, views
from solar_server.auth import TokenVerifier, check_plug_key, check_scheduler, google_verifier
from solar_server.config import Settings
from solar_server.sources import LiveSources, Sources
from solar_server.store import PLUG, FirestoreStore, Store

# The built dashboard (web/dist). The container sets SOLAR_WEB_DIST; locally
# it's found next to the source tree.
WEB_DIST = Path(
    os.environ.get("SOLAR_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist")
)


class PlugReport(BaseModel):
    t: int
    on: bool
    reason: str
    w: float | None = None
    wh: float | None = None
    index: float | None = None
    plan_at: int | None = None


def create_app(
    settings: Settings,
    store: Store,
    sources: Sources,
    verify: TokenVerifier = google_verifier,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    app = FastAPI(title="Solar Farm", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "role": settings.role}

    if settings.role == "edge":
        _edge_routes(app, settings, store, sources, verify, clock)
    else:
        _web_routes(app, store, clock)
    return app


def _edge_routes(app, settings, store, sources, verify, clock) -> None:
    def now() -> datetime:
        return datetime.fromtimestamp(clock(), UTC)

    @app.get("/plug/plan")
    def plug_plan(x_plug_key: Annotated[str | None, Header()] = None) -> dict:
        check_plug_key(x_plug_key, settings.plug_key)
        p = tasks.plug_plan(store)
        if p is None:
            raise HTTPException(status_code=503, detail="no plan yet")
        return p

    @app.post("/plug/report", status_code=204)
    def plug_report(
        report: PlugReport, x_plug_key: Annotated[str | None, Header()] = None
    ) -> Response:
        check_plug_key(x_plug_key, settings.plug_key)
        item: dict[str, Any] = report.model_dump(exclude_none=True)
        item["received"] = int(clock())
        store.append(PLUG, item)
        return Response(status_code=204)

    @app.post("/tasks/collect")
    def collect(request: Request) -> dict:
        check_scheduler(request, settings.scheduler_sa, verify)
        return tasks.collect(store, sources, now())

    @app.post("/tasks/plan")
    def plan(request: Request) -> dict:
        check_scheduler(request, settings.scheduler_sa, verify)
        p = tasks.plan(store, sources, settings, now())
        return {"windows": p["windows"], "generated_at": p["generated_at"]}


def _web_routes(app, store, clock) -> None:
    @app.get("/api/now")
    def api_now() -> dict:
        return views.now_view(store, int(clock()))

    @app.get("/api/timeline")
    def api_timeline(past_hours: Annotated[int, Query(ge=1, le=168)] = 24) -> dict:
        return views.timeline_view(store, int(clock()), past_hours)

    @app.get("/api/accuracy")
    def api_accuracy(
        lead_hours: Annotated[int, Query(ge=1, le=23)] = 6,
        past_hours: Annotated[int, Query(ge=1, le=168)] = 24,
    ) -> dict:
        return views.accuracy_view(store, int(clock()), lead_hours, past_hours)

    @app.get("/api/daily")
    def api_daily(days: Annotated[int, Query(ge=1, le=60)] = 14) -> dict:
        return views.daily_view(store, int(clock()), days)

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:

        @app.get("/")
        def placeholder() -> dict:
            return {"message": "Dashboard not built yet; the API is at /api/now."}


def main() -> FastAPI:
    """Entry point for uvicorn --factory."""
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    return create_app(settings, FirestoreStore(settings.project), LiveSources(settings))
