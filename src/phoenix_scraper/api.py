"""FastAPI app factory exposing the prompt-mining store, pipeline, and exports."""

import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Security
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security.api_key import APIKeyHeader

from . import (
    __version__,
    insights,
    insights_llm,
    insights_quality,
    insights_users,
    skill_coverage,
)
from . import (
    annotations as annotations_mod,
)
from .config import Settings, load_settings
from .costs import cost_summary
from .evaluations import check_names
from .export import frame_to_csv_text, write_markdown_report
from .fixtures import seed_demo
from .models import QueryFilters
from .phoenix_client import PhoenixClientWrapper
from .pipeline import ANALYSIS_SPAN_LIMIT, run_analysis
from .scraper import scrape_once
from .skills import load_all_skills
from .storage import Store

_DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"

Fmt = Literal["json", "csv"]

# Span columns the quality rollup may group by — an allowlist, since the value
# reaches a groupby on a joined frame.
_QUALITY_DIMENSIONS = frozenset(
    {"user_id", "model_name", "workflow_stage", "asset_class", "project", "span_kind"}
)

# Row ceiling for the quality endpoints. Each span contributes one row per
# applicable check, so this must cover ANALYSIS_SPAN_LIMIT spans times the
# number of registered checks — otherwise a rollup quietly describes a
# truncated corpus while presenting itself as the whole picture.
EVALUATION_ROW_LIMIT = ANALYSIS_SPAN_LIMIT * 20

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

    def analysis_filters(
        project: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        stage: str | None = None,
        asset_class: str | None = None,
        model_name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        search: str | None = None,
        # Analytics must see the same corpus the analysis ran over — a 1000-span
        # default here silently skews every panel above 1000 spans.
        limit: int = Query(default=ANALYSIS_SPAN_LIMIT, ge=1, le=1_000_000),
    ) -> QueryFilters:
        return span_filters(
            project, start, end, stage, asset_class, model_name, session_id,
            user_id, search, limit,
        )

    AnalysisFiltersDep = Annotated[QueryFilters, Depends(analysis_filters)]

    def quality_filters(
        project: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        stage: str | None = None,
        asset_class: str | None = None,
        model_name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        search: str | None = None,
        # evaluations_frame counts CHECK ROWS, and one span yields a row per
        # applicable check — so the span-sized analysis limit would truncate
        # every quality rollup above ~8k spans while still looking complete.
        limit: int = Query(default=EVALUATION_ROW_LIMIT, ge=1, le=EVALUATION_ROW_LIMIT),
    ) -> QueryFilters:
        return span_filters(
            project, start, end, stage, asset_class, model_name, session_id,
            user_id, search, limit,
        )

    QualityFiltersDep = Annotated[QueryFilters, Depends(quality_filters)]

    @app.middleware("http")
    async def security_guard(request, call_next):
        # CSRF: browsers attach Origin to cross-site POSTs; reject any that
        # don't match the host we're serving on. Non-browser clients (curl,
        # scripts) send no Origin and pass through.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None:
                from urllib.parse import urlsplit

                if urlsplit(origin).netloc != request.headers.get("host", ""):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin request rejected"},
                    )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    def dashboard() -> HTMLResponse:
        # Static shell only — every piece of data it shows comes from the
        # protected endpoints below, so auth still applies.
        return HTMLResponse(_DASHBOARD_PATH.read_text(encoding="utf-8"))

    @protected.get("/filters/options")
    def filter_options() -> dict[str, Any]:
        with open_store() as store:
            return store.distinct_options()

    @protected.get("/overview")
    def overview(filters: AnalysisFiltersDep) -> dict[str, Any]:
        with open_store() as store:
            spans = store.spans_frame(filters)
            n_clusters = len(store.clusters_frame(limit=100_000))
            n_matches = len(store.matches_frame())
            n_proposals = len(store.proposals_frame())
        if spans.empty:
            return {"n_spans": 0, "n_clusters": n_clusters, "n_matches": n_matches,
                    "n_proposals": n_proposals}
        errors = insights.error_mask(spans["status_code"])
        return {
            "n_spans": int(len(spans)),
            "n_traces": int(spans["trace_id"].nunique()),
            "n_sessions": int(spans["session_id"].dropna().nunique()),
            "n_users": int(spans["user_id"].dropna().nunique()),
            "total_tokens": int(spans["tokens_total"].fillna(0).sum()),
            "total_cost_usd": float(spans["cost_usd"].fillna(0.0).sum()),
            "error_rate": float(errors.mean()),
            "avg_latency_ms": float(spans["latency_ms"].dropna().mean())
            if spans["latency_ms"].notna().any()
            else None,
            "first_span": str(spans["start_time"].min()),
            "last_span": str(spans["start_time"].max()),
            "n_clusters": n_clusters,
            "n_matches": n_matches,
            "n_proposals": n_proposals,
        }

    @protected.get("/insights/traces")
    def insights_traces(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights.trace_profiles(store.spans_frame(filters))
        return _frame_response(df, fmt, "trace_profiles")

    @protected.get("/insights/questions")
    def insights_questions(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights.question_taxonomy(store.spans_frame(filters))
        return _frame_response(df, fmt, "question_taxonomy")

    @protected.get("/insights/friction")
    def insights_friction(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights.session_friction(store.spans_frame(filters))
        return _frame_response(df, fmt, "session_friction")

    @protected.get("/insights/efficiency")
    def insights_efficiency(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights.cluster_efficiency(
                store.spans_frame(filters),
                store.clusters_frame(limit=100_000),
                store.cluster_members_frame(),
            )
        return _frame_response(df, fmt, "cluster_efficiency")

    @protected.get("/users")
    def users_list(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights_users.user_profiles(store.spans_frame(filters))
        return _frame_response(df, fmt, "users")

    @protected.get("/users/questions")
    def users_questions(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights_users.user_question_matrix(store.spans_frame(filters))
        return _frame_response(df, fmt, "user_questions")

    @protected.get("/insights/activity")
    def insights_activity(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights_users.daily_activity(store.spans_frame(filters))
        return _frame_response(df, fmt, "daily_activity")

    @protected.get("/insights/tools")
    def insights_tools(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights_llm.tool_usage(store.spans_frame(filters))
        return _frame_response(df, fmt, "tool_usage")

    @protected.get("/insights/models")
    def insights_models(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights_llm.model_usage(store.spans_frame(filters))
        return _frame_response(df, fmt, "model_usage")

    @protected.get("/insights/flows")
    def insights_flows(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights_llm.agent_flows(store.spans_frame(filters))
        return _frame_response(df, fmt, "agent_flows")

    @protected.get("/insights/breakdown")
    def insights_breakdown(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            df = insights_llm.stage_asset_breakdown(store.spans_frame(filters))
        return _frame_response(df, fmt, "stage_asset_breakdown")

    @protected.get("/insights/skill-health")
    def insights_skill_health(filters: AnalysisFiltersDep, fmt: Fmt = "json") -> Response:
        with open_store() as store:
            efficiency = insights.cluster_efficiency(
                store.spans_frame(filters),
                store.clusters_frame(limit=100_000),
                store.cluster_members_frame(),
            )
            df = insights.skill_health(efficiency, store.matches_frame())
        return _frame_response(df, fmt, "skill_health")

    @protected.get("/quality/overview")
    def quality_overview(filters: QualityFiltersDep) -> dict[str, Any]:
        with open_store() as store:
            df = store.evaluations_frame(filters)
        return insights_quality.quality_overview(df)

    @protected.get("/quality/checks")
    def quality_checks(filters: QualityFiltersDep, fmt: Fmt = "json") -> Response:
        """Per-check scoreboard: how often each validation applied and failed."""
        with open_store() as store:
            df = insights_quality.quality_summary(store.evaluations_frame(filters))
        return _frame_response(df, fmt, "quality_checks")

    @protected.get("/quality/by")
    def quality_by(
        filters: QualityFiltersDep,
        dimension: str = "user_id",
        fmt: Fmt = "json",
    ) -> Response:
        """Fail rates grouped by any span dimension (user, model, stage, asset class)."""
        if dimension not in _QUALITY_DIMENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"dimension must be one of {', '.join(sorted(_QUALITY_DIMENSIONS))}",
            )
        with open_store() as store:
            df = insights_quality.quality_by_dimension(
                store.evaluations_frame(filters), dimension
            )
        return _frame_response(df, fmt, f"quality_by_{dimension}")

    @protected.get("/quality/failures")
    def quality_failures(
        filters: QualityFiltersDep,
        top: int = Query(default=200, ge=1, le=10_000),
        fmt: Fmt = "json",
    ) -> Response:
        """The failing spans themselves — prompt, answer, and why each check failed."""
        with open_store() as store:
            df = insights_quality.failing_spans(store.evaluations_frame(filters), limit=top)
        return _frame_response(df, fmt, "quality_failures")

    @protected.get("/quality/by-prompt")
    def quality_by_prompt(filters: QualityFiltersDep, fmt: Fmt = "json") -> Response:
        """Prompt patterns ranked by how badly the agent answers them."""
        with open_store() as store:
            df = insights_quality.quality_by_cluster(
                store.evaluations_frame(filters),
                store.clusters_frame(limit=100_000),
                store.cluster_members_frame(),
            )
        return _frame_response(df, fmt, "quality_by_prompt")

    @protected.get("/quality/evaluations")
    def quality_evaluations(filters: QualityFiltersDep, fmt: Fmt = "json") -> Response:
        """Raw judgements — one row per (span, check), for validating the validators."""
        with open_store() as store:
            df = store.evaluations_frame(filters)
        return _frame_response(df, fmt, "evaluations")

    @protected.get("/quality/catalog")
    def quality_catalog() -> list[dict[str, str]]:
        """The registered code checks, so the UI can describe what was validated."""
        return [{"check": name, "target": target} for name, target in check_names()]

    @protected.post("/annotations/pull")
    def annotations_pull() -> dict[str, Any]:
        """Pull HUMAN/LLM span annotations from Phoenix for the stored spans."""
        client = _require_phoenix()
        with open_store() as store:
            report = annotations_mod.pull_annotations(store, client, settings)
        return report.model_dump(mode="json")

    @protected.post("/annotations/push")
    def annotations_push(only_failures: bool = True) -> dict[str, Any]:
        """Push locally computed CODE checks back to Phoenix as span annotations."""
        client = _require_phoenix()
        with open_store() as store:
            report = annotations_mod.push_annotations(
                store, client, settings, only_failures=only_failures
            )
        return report.model_dump(mode="json")

    def _require_phoenix() -> PhoenixClientWrapper:
        client = PhoenixClientWrapper(settings)
        if not client.available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Phoenix is not available: set PHOENIX_COLLECTOR_ENDPOINT and "
                    "install the 'live' extra (arize-phoenix-client)."
                ),
            )
        return client

    def _coverage_inputs(store: Store) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(annotated clusters, deltas vs the previous run) — the coverage basis."""
        skills = load_all_skills(settings)
        annotated = skill_coverage.annotate_coverage(
            store.clusters_frame(limit=100_000),
            store.matches_frame(),
            skills,
            threshold=settings.skill_coverage_threshold,
        )
        latest = store.previous_run_id()
        deltas = skill_coverage.cluster_deltas(
            store.run_snapshot_frame(latest),
            store.run_snapshot_frame(store.previous_run_id(latest)),
        )
        return annotated, deltas

    @protected.get("/skills/coverage")
    def skills_coverage(fmt: Fmt = "json") -> Response:
        """Per skill file: how much of what it is asked does it demonstrate?"""
        with open_store() as store:
            annotated, _ = _coverage_inputs(store)
            df = skill_coverage.skill_coverage(annotated)
        return _frame_response(df, fmt, "skill_coverage")

    @protected.get("/skills/uncovered")
    def skills_uncovered(fmt: Fmt = "json") -> Response:
        """The blind spots: real questions the matched skill file does not show."""
        with open_store() as store:
            annotated, deltas = _coverage_inputs(store)
            df = skill_coverage.uncovered_queries(annotated, deltas)
        return _frame_response(df, fmt, "skill_uncovered")

    @protected.get("/skills/updates")
    def skills_updates(fmt: Fmt = "json") -> Response:
        """Paste-ready example_prompts/keywords additions, per skill file."""
        with open_store() as store:
            annotated, deltas = _coverage_inputs(store)
            df = skill_coverage.suggested_updates(
                skill_coverage.uncovered_queries(annotated, deltas),
                load_all_skills(settings),
                max_prompts=settings.max_suggested_prompts,
            )
        if fmt == "csv":
            # Lists don't survive a CSV cell; join them for the spreadsheet view.
            df = df.assign(
                new_prompts=df["new_prompts"].map(lambda v: " | ".join(v)),
                new_keywords=df["new_keywords"].map(lambda v: ", ".join(v)),
            ) if not df.empty else df
        return _frame_response(df, fmt, "skill_updates")

    @protected.get("/skills/updates.md", response_class=Response)
    def skills_updates_markdown() -> Response:
        """The same suggestions as one paste-ready markdown document."""
        with open_store() as store:
            annotated, deltas = _coverage_inputs(store)
            df = skill_coverage.suggested_updates(
                skill_coverage.uncovered_queries(annotated, deltas),
                load_all_skills(settings),
                max_prompts=settings.max_suggested_prompts,
            )
        return Response(
            content=skill_coverage.updates_markdown(df), media_type="text/markdown"
        )

    @protected.get("/runs")
    def runs_list(fmt: Fmt = "json") -> Response:
        """Recorded analysis runs, newest first — the basis for run-over-run diffs."""
        with open_store() as store:
            df = store.runs_frame()
        return _frame_response(df, fmt, "runs")

    @protected.get("/runs/delta")
    def runs_delta(fmt: Fmt = "json") -> Response:
        """What users started (and stopped) asking since the previous run."""
        with open_store() as store:
            latest = store.previous_run_id()
            df = skill_coverage.cluster_deltas(
                store.run_snapshot_frame(latest),
                store.run_snapshot_frame(store.previous_run_id(latest)),
            )
        return _frame_response(df, fmt, "run_delta")

    @protected.post("/analyze/run")
    def analyze_run() -> dict[str, Any]:
        """Re-run the mining pipeline over the stored spans."""
        with open_store() as store:
            result = run_analysis(store, settings)
        return {
            "run_id": result.run_id,
            "previous_run_id": result.previous_run_id,
            "n_spans_analyzed": result.n_spans_analyzed,
            "clusters": len(result.clusters),
            "matches": len(result.matches),
            "proposals": len(result.proposals),
            "sessions": len(result.sessions),
            "evaluations": len(result.evaluations),
        }

    @protected.post("/report/run")
    def report_run() -> dict[str, Any]:
        """Re-run the analysis and write the markdown report to the export dir."""
        with open_store() as store:
            result = run_analysis(store, settings)
            annotated, deltas = _coverage_inputs(store)
        updates = skill_coverage.suggested_updates(
            skill_coverage.uncovered_queries(annotated, deltas),
            load_all_skills(settings),
            max_prompts=settings.max_suggested_prompts,
        )
        report_path = write_markdown_report(
            result, settings.export_dir / "report.md", updates
        )
        updates_path = settings.export_dir / "skill_updates.md"
        updates_path.write_text(
            skill_coverage.updates_markdown(updates), encoding="utf-8"
        )
        return {
            "report": str(report_path),
            "skill_updates": str(updates_path),
            "n_spans_analyzed": result.n_spans_analyzed,
            "skills_with_gaps": int(len(updates)),
        }

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
        client = _require_phoenix()
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
