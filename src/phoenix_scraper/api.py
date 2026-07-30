"""FastAPI app factory exposing the prompt-mining store, pipeline, and exports."""

import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security.api_key import APIKeyHeader

from . import __version__
from .config import Settings, load_settings
from .costs import cost_summary
from .export import frame_to_csv_text
from .fixtures import seed_demo
from .models import QueryFilters
from .phoenix_client import PhoenixClientWrapper
from .pipeline import run_analysis
from .scraper import scrape_once
from .storage import Store

Fmt = Literal["json", "csv"]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app(settings: Settings) -> FastAPI:
    """Build the API around one Settings instance (dependency-injectable for tests)."""
    app = FastAPI(title="Pheonix prompt miner", version=__version__)
    app.state.settings = settings

    def require_api_key(provided: str | None = Security(_api_key_header)) -> None:
        # Open mode when no key is configured (loopback-only; cli.serve enforces that).
        if settings.api_key is None:
            return
        if provided is None or not secrets.compare_digest(provided, settings.api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    protected = APIRouter(dependencies=[Depends(require_api_key)])

    @contextmanager
    def open_store() -> Iterator[Store]:
        # A fresh Store per request keeps the sqlite connection on the handler thread.
        store = Store(settings.db_path)
        try:
            yield store
        finally:
            store.close()

    def span_filters(
        project: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        stage: str | None = None,
        asset_class: str | None = None,
        model_name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        search: str | None = None,
        limit: int = Query(default=1000, ge=1, le=100_000),
    ) -> QueryFilters:
        return QueryFilters(
            project=project,
            start=_utc(start),
            end=_utc(end),
            workflow_stage=stage,
            asset_class=asset_class,
            model_name=model_name,
            session_id=session_id,
            user_id=user_id,
            search=search,
            limit=limit,
        )

    FiltersDep = Annotated[QueryFilters, Depends(span_filters)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @protected.post("/demo/seed")
    def demo_seed(n_sessions: int = 60, seed: int = 42) -> dict[str, Any]:
        with open_store() as store:
            report = seed_demo(store, n_sessions=n_sessions, seed=seed)
            result = run_analysis(store, settings)
        return {
            "report": report.model_dump(mode="json"),
            "clusters": len(result.clusters),
            "matches": len(result.matches),
            "proposals": len(result.proposals),
            "sessions": len(result.sessions),
            "n_spans_analyzed": result.n_spans_analyzed,
        }

    @protected.post("/scrape/run")
    def scrape_run() -> dict[str, Any]:
        client = PhoenixClientWrapper(settings)
        if not client.available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Phoenix is not available: set PHOENIX_COLLECTOR_ENDPOINT and "
                    "install the 'live' extra (arize-phoenix-client)."
                ),
            )
        with open_store() as store:
            report = scrape_once(store, client, settings)
        return report.model_dump(mode="json")

    @protected.get("/prompts/frequent")
    def prompts_frequent(
        min_count: int = Query(default=1, ge=1),
        limit: int = Query(default=500, ge=1, le=100_000),
        fmt: Fmt = "json",
    ) -> Response:
        with open_store() as store:
            df = store.clusters_frame(min_count=min_count, limit=limit)
        return _frame_response(df, fmt, "prompts_frequent")

    @protected.get("/skills/matches")
    def skills_matches(fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = store.matches_frame()
        return _frame_response(df, fmt, "skill_matches")

    @protected.get("/skills/gaps")
    def skills_gaps(fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = store.proposals_frame()
        return _frame_response(df, fmt, "skill_gaps")

    @protected.get("/sessions")
    def sessions_list(fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = store.sessions_frame()
        return _frame_response(df, fmt, "sessions")

    @protected.get("/costs/summary")
    def costs_summary_route(
        filters: FiltersDep,
        group_by: str = "model_name",
        fmt: Fmt = "json",
    ) -> Response:
        columns = [c.strip() for c in group_by.split(",") if c.strip()]
        with open_store() as store:
            spans_df = store.spans_frame(filters)
        try:
            df = cost_summary(spans_df, columns)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _frame_response(df, fmt, "costs_summary")

    @protected.get("/spans")
    def spans_list(filters: FiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = store.spans_frame(filters)
        return _frame_response(df, fmt, "spans")

    app.include_router(protected)
    return app


def create_app_default() -> FastAPI:
    """Zero-arg factory for `uvicorn phoenix_scraper.api:create_app_default --factory`."""
    return create_app(load_settings())


# ---- helpers -------------------------------------------------------------------


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _frame_response(df: pd.DataFrame, fmt: Fmt, name: str) -> Response:
    if fmt == "csv":
        # In-memory: no shared temp file (concurrent requests must never race on one
        # path) and no sensitive data left behind on disk.
        return Response(
            content=frame_to_csv_text(df),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    # to_json handles NaN -> null and datetimes -> ISO strings.
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return JSONResponse(content=records)
