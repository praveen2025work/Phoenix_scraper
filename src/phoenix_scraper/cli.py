"""Typer CLI: demo, seed, scrape, ingest, analyze, report, export, serve, doctor."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import typer

from . import annotations as annotations_mod
from . import evaluations as evaluations_mod
from . import export as export_mod
from . import fixtures, insights_quality, pipeline, scraper, skill_coverage
from . import skills as skills_mod
from .config import Settings, load_settings
from .models import (
    AnalysisResult,
    AnnotationSyncReport,
    PromptCluster,
    QueryFilters,
    ScrapeReport,
)
from .phoenix_client import PhoenixClientWrapper
from .storage import Store

app = typer.Typer(
    name="pheonix",
    help="Mine Arize Phoenix traces for frequent prompts, costs, and skill gaps.",
    no_args_is_help=True,
)


@app.callback()
def _init_logging() -> None:
    """Surface this package's INFO logs (e.g. which CA bundle TLS trusts)."""
    pkg_logger = logging.getLogger("phoenix_scraper")
    if not pkg_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        pkg_logger.addHandler(handler)
        pkg_logger.setLevel(logging.INFO)

_TOP_N = 10
_PROMPT_PREVIEW_CHARS = 70
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class ExportWhat(StrEnum):
    spans = "spans"
    clusters = "clusters"
    matches = "matches"
    proposals = "proposals"
    sessions = "sessions"
    evaluations = "evaluations"
    coverage = "coverage"
    uncovered = "uncovered"


class ExportFmt(StrEnum):
    csv = "csv"
    json = "json"
    parquet = "parquet"


# Module-level option singletons keep function defaults free of call expressions.
DbOpt = typer.Option(None, "--db", help="Override the SQLite database path.")
ExportDirOpt = typer.Option(None, "--export-dir", help="Override the export directory.")
ProjectOpt = typer.Option(None, "--project", help="Filter/scope to one project.")
StartOpt = typer.Option(None, "--start", help="Only spans starting at/after this time (UTC).")
EndOpt = typer.Option(None, "--end", help="Only spans starting before this time (UTC).")
StageOpt = typer.Option(None, "--stage", help="Filter by workflow stage.")
AssetClassOpt = typer.Option(None, "--asset-class", help="Filter by asset class.")
SessionsOpt = typer.Option(60, "--sessions", help="Number of synthetic sessions.")
SeedOpt = typer.Option(42, "--seed", help="Deterministic RNG seed.")
ReportPathOpt = typer.Option(
    None, "--report", help="Markdown report path (default: <export-dir>/report.md)."
)
JsonlPathArg = typer.Argument(..., exists=True, dir_okay=False, readable=True)
IngestProjectOpt = typer.Option("default", "--project", help="Project tag for ingested spans.")
SearchOpt = typer.Option(None, "--search", help="Substring match on input text.")
MinCountOpt = typer.Option(1, "--min-count", help="Minimum cluster count.")
AnalyzeLimitOpt = typer.Option(100_000, "--limit", help="Max spans to analyze.")
ExportLimitOpt = typer.Option(10_000, "--limit", help="Max rows to export.")
OutOpt = typer.Option(None, "--out", help="Markdown output path.")
WhatOpt = typer.Option(..., "--what", help="Which table to export.")
FmtOpt = typer.Option(ExportFmt.csv, "--fmt", help="Export file format.")
HostOpt = typer.Option("127.0.0.1", "--host")
PortOpt = typer.Option(8000, "--port")
SinceOpt = typer.Option(
    None,
    "--since",
    help="First scrape only: pull spans starting at/after this time (UTC) instead of "
    "the full project history. Ignored once a watermark exists.",
)
PullAnnotationsOpt = typer.Option(
    False,
    "--pull-annotations",
    help="Also fetch HUMAN/LLM span annotations from Phoenix (needs a live connection).",
)
PushAnnotationsOpt = typer.Option(
    False,
    "--push",
    help="Write the failing code checks back to Phoenix as CODE span annotations.",
)
PushAllOpt = typer.Option(
    False,
    "--push-all",
    help="With --push, send passing checks too instead of failures only.",
)
UserOpt = typer.Option(None, "--user", help="Filter by user id.")
WriteUpdatesOpt = typer.Option(
    False,
    "--write",
    help="Also write the paste-ready blocks to <export-dir>/skill_updates.md.",
)


@app.command()
def demo(
    sessions: int = SessionsOpt,
    seed: int = SeedOpt,
    db: Path | None = DbOpt,
    export_dir: Path | None = ExportDirOpt,
    report_path: Path | None = ReportPathOpt,
) -> None:
    """Seed fixture traffic, run the full analysis, and write the markdown report."""
    settings = _settings(db=db, export_dir=export_dir)
    with _open_store(settings) as store:
        scrape_report = fixtures.seed_demo(store, n_sessions=sessions, seed=seed)
        result = pipeline.run_analysis(store, settings)
        _, _, updates = _coverage_tables(store, settings)
    out_path = report_path or settings.export_dir / "report.md"
    export_mod.write_markdown_report(result, out_path, updates)

    _echo_scrape(scrape_report)
    _echo_summary(result)
    _echo_top_prompts(result.clusters)
    typer.echo("")
    typer.echo(f"Database: {settings.db_path}")
    typer.echo(f"Report:   {out_path}")
    if len(updates):
        typer.echo(
            f"Skill gaps: {len(updates)} skill files are asked questions they "
            f"don't demonstrate — `pheonix coverage` for the lines to add."
        )


@app.command()
def seed(
    sessions: int = SessionsOpt,
    seed: int = SeedOpt,
    db: Path | None = DbOpt,
) -> None:
    """Insert deterministic fixture spans (no analysis)."""
    settings = _settings(db=db)
    with _open_store(settings) as store:
        report = fixtures.seed_demo(store, n_sessions=sessions, seed=seed)
    _echo_scrape(report)


@app.command()
def scrape(
    project: str | None = ProjectOpt,
    since: datetime | None = SinceOpt,
    db: Path | None = DbOpt,
) -> None:
    """Incrementally pull spans from a live Phoenix server (watermarked)."""
    settings = _settings(db=db, project=project)
    client = PhoenixClientWrapper(settings)
    if not client.available():
        typer.secho(
            "Phoenix is not available: set PHOENIX_COLLECTOR_ENDPOINT and install "
            "the 'live' extra (arize-phoenix-client).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    with _open_store(settings) as store:
        report = scraper.scrape_once(store, client, settings, since=_utc(since))
    _echo_scrape(report)


@app.command()
def ingest(
    path: Path = JsonlPathArg,
    project: str = IngestProjectOpt,
    db: Path | None = DbOpt,
) -> None:
    """Ingest spans offline from a JSONL file (one JSON span per line)."""
    settings = _settings(db=db)
    with _open_store(settings) as store:
        report = scraper.ingest_jsonl(store, path, project)
    _echo_scrape(report)


@app.command()
def analyze(
    project: str | None = ProjectOpt,
    start: datetime | None = StartOpt,
    end: datetime | None = EndOpt,
    stage: str | None = StageOpt,
    asset_class: str | None = AssetClassOpt,
    limit: int = AnalyzeLimitOpt,
    db: Path | None = DbOpt,
) -> None:
    """Run the analysis pipeline over stored spans and persist the results."""
    settings = _settings(db=db)
    filters = _filters(project, start, end, stage, asset_class, limit)
    with _open_store(settings) as store:
        result = pipeline.run_analysis(store, settings, filters=filters)
    _echo_summary(result)
    _echo_top_prompts(result.clusters)


@app.command()
def evaluate(
    project: str | None = ProjectOpt,
    start: datetime | None = StartOpt,
    end: datetime | None = EndOpt,
    stage: str | None = StageOpt,
    asset_class: str | None = AssetClassOpt,
    user: str | None = UserOpt,
    limit: int = AnalyzeLimitOpt,
    pull_annotations: bool = PullAnnotationsOpt,
    push: bool = PushAnnotationsOpt,
    push_all: bool = PushAllOpt,
    db: Path | None = DbOpt,
) -> None:
    """Validate stored LLM outputs and user prompts, and sync annotations with Phoenix.

    Runs the deterministic CODE checks over every stored span (no model calls),
    optionally pulls the HUMAN/LLM annotations Phoenix already holds, and
    optionally pushes the failures back so they show against the spans in the
    Phoenix UI.
    """
    settings = _settings(db=db, project=project)
    filters = _filters(project, start, end, stage, asset_class, limit, user_id=user)
    with _open_store(settings) as store:
        if pull_annotations:
            _echo_sync(
                annotations_mod.pull_annotations(
                    store, _live_client(settings), settings, filters
                )
            )
        spans_df = store.spans_frame(filters)
        results = evaluations_mod.evaluate_spans(spans_df, settings)
        store.replace_local_evaluations(results)
        summary = insights_quality.quality_summary(store.evaluations_frame(filters))
        overview = insights_quality.quality_overview(store.evaluations_frame(filters))
        if push:
            _echo_sync(
                annotations_mod.push_annotations(
                    store, _live_client(settings), settings, filters,
                    only_failures=not push_all,
                )
            )
    _echo_quality(overview, summary)


@app.command()
def coverage(
    db: Path | None = DbOpt,
    export_dir: Path | None = ExportDirOpt,
    write: bool = WriteUpdatesOpt,
) -> None:
    """Show what each skill FILE is asked but does not demonstrate.

    A prompt cluster can match a skill on keywords alone while none of that
    skill's example_prompts shows the phrasing users actually type. Those are
    the file's blind spots — printed here with the concrete lines to add.
    """
    settings = _settings(db=db, export_dir=export_dir)
    with _open_store(settings) as store:
        annotated, deltas, updates = _coverage_tables(store, settings)
        coverage_df = skill_coverage.skill_coverage(annotated)
    _echo_coverage(coverage_df, updates)
    if write:
        out_path = settings.export_dir / "skill_updates.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            skill_coverage.updates_markdown(updates), encoding="utf-8"
        )
        typer.echo("")
        typer.echo(f"Paste-ready updates written to {out_path}")


@app.command()
def report(
    out: Path | None = OutOpt,
    db: Path | None = DbOpt,
    export_dir: Path | None = ExportDirOpt,
) -> None:
    """Run the analysis and write the human-readable markdown report."""
    settings = _settings(db=db, export_dir=export_dir)
    with _open_store(settings) as store:
        result = pipeline.run_analysis(store, settings)
        _, _, updates = _coverage_tables(store, settings)
    out_path = out or settings.export_dir / "report.md"
    export_mod.write_markdown_report(result, out_path, updates)
    updates_path = settings.export_dir / "skill_updates.md"
    updates_path.parent.mkdir(parents=True, exist_ok=True)
    updates_path.write_text(skill_coverage.updates_markdown(updates), encoding="utf-8")
    typer.echo(f"Report written to {out_path}")
    typer.echo(f"Skill updates written to {updates_path}")


@app.command()
def export(
    what: ExportWhat = WhatOpt,
    fmt: ExportFmt = FmtOpt,
    project: str | None = ProjectOpt,
    start: datetime | None = StartOpt,
    end: datetime | None = EndOpt,
    stage: str | None = StageOpt,
    asset_class: str | None = AssetClassOpt,
    search: str | None = SearchOpt,
    min_count: int = MinCountOpt,
    limit: int = ExportLimitOpt,
    db: Path | None = DbOpt,
    export_dir: Path | None = ExportDirOpt,
) -> None:
    """Export one analysis table to <export-dir>/<what>.<fmt>."""
    settings = _settings(db=db, export_dir=export_dir)
    with _open_store(settings) as store:
        if what is ExportWhat.spans:
            filters = _filters(project, start, end, stage, asset_class, limit, search)
            df = store.spans_frame(filters)
        elif what is ExportWhat.clusters:
            df = store.clusters_frame(min_count=min_count, limit=limit)
        elif what is ExportWhat.matches:
            df = store.matches_frame()
        elif what is ExportWhat.proposals:
            df = store.proposals_frame()
        elif what is ExportWhat.evaluations:
            filters = _filters(project, start, end, stage, asset_class, limit, search)
            df = store.evaluations_frame(filters)
        elif what in (ExportWhat.coverage, ExportWhat.uncovered):
            annotated, deltas, _ = _coverage_tables(store, settings)
            df = (
                skill_coverage.skill_coverage(annotated)
                if what is ExportWhat.coverage
                else skill_coverage.uncovered_queries(annotated, deltas)
            )
        else:
            df = store.sessions_frame()
    path = export_mod.export_frame(df, settings.export_dir, what.value, fmt.value)
    typer.echo(f"Exported {len(df)} {what.value} rows to {path}")


@app.command()
def doctor() -> None:
    """Print connection/TLS diagnostics: endpoint, CA bundle contents, live probe."""
    from pydantic import ValidationError

    from . import diagnostics

    try:
        settings = _settings()
    except ValidationError as exc:
        for error in exc.errors():
            loc = ".".join(str(part) for part in error["loc"]) or "settings"
            typer.secho(f"config: INVALID — {loc}: {error['msg']} (check .env)",
                        fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    for line in diagnostics.doctor_report(settings):
        typer.echo(line)


@app.command()
def serve(
    host: str = HostOpt,
    port: int = PortOpt,
    db: Path | None = DbOpt,
    export_dir: Path | None = ExportDirOpt,
) -> None:
    """Serve the FastAPI app with uvicorn."""
    import uvicorn

    from .api import create_app

    settings = _settings(db=db, export_dir=export_dir)
    if host not in _LOOPBACK_HOSTS and not settings.api_key:
        typer.secho(
            "Refusing to bind a non-loopback host without auth: scraped prompts can "
            "contain sensitive data. Set PHEONIX_API_KEY (clients send it as X-API-Key) "
            f"or serve on 127.0.0.1 instead of {host}.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(f"Serving on http://{host}:{port} (db: {settings.db_path})")
    uvicorn.run(create_app(settings), host=host, port=port)


# ---- helpers -------------------------------------------------------------------


def _settings(
    db: Path | None = None,
    export_dir: Path | None = None,
    project: str | None = None,
) -> Settings:
    base = load_settings()
    updates: dict[str, object] = {
        key: value
        for key, value in (("db_path", db), ("export_dir", export_dir), ("project", project))
        if value is not None
    }
    return base.model_copy(update=updates) if updates else base


@contextmanager
def _open_store(settings: Settings) -> Iterator[Store]:
    store = Store(settings.db_path)
    try:
        yield store
    finally:
        store.close()


def _filters(
    project: str | None,
    start: datetime | None,
    end: datetime | None,
    stage: str | None,
    asset_class: str | None,
    limit: int,
    search: str | None = None,
    user_id: str | None = None,
) -> QueryFilters:
    return QueryFilters(
        project=project,
        start=_utc(start),
        end=_utc(end),
        workflow_stage=stage,
        asset_class=asset_class,
        search=search,
        user_id=user_id,
        limit=limit,
    )


def _coverage_tables(store: Store, settings: Settings):
    """(annotated clusters, run deltas, suggested updates) from the stored analysis."""
    skills = skills_mod.load_all_skills(settings)
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
    updates = skill_coverage.suggested_updates(
        skill_coverage.uncovered_queries(annotated, deltas),
        skills,
        max_prompts=settings.max_suggested_prompts,
    )
    return annotated, deltas, updates


def _echo_coverage(coverage_df, updates_df) -> None:
    """Coverage per skill file, then the concrete lines to add to each."""
    if not len(coverage_df):
        typer.echo(
            "No matched skills yet — run `pheonix analyze` first, and point "
            "PHEONIX_SKILLS_CATALOG / PHEONIX_SKILLS_DIRS at your real skills."
        )
        return
    typer.echo("Skill coverage — of the asks routed to each skill, how many does it show?")
    typer.echo("")
    # Skill AND file: a SKILL.md tree gives one skill per file, but a shared
    # catalog yaml gives many, and the file alone would name them all the same.
    header = (
        f"{'skill':<26} {'file':<22} {'asks':>5} {'shown':>6} {'gap':>4} "
        f"{'cover':>6}  top gap"
    )
    typer.echo(header)
    typer.echo("-" * (len(header) + 30))
    for row in coverage_df.to_dict("records"):
        gap = row["top_gap"].replace("\n", " ")
        if len(gap) > _PROMPT_PREVIEW_CHARS:
            gap = gap[: _PROMPT_PREVIEW_CHARS - 1] + "…"
        typer.echo(
            f"{str(row['skill_name'])[:26]:<26} {str(row['source_file'])[:22]:<22} "
            f"{row['n_asks']:>5} {row['n_covered_asks']:>6} "
            f"{row['n_uncovered_asks']:>4} {row['coverage']:>5.0%}  {gap}"
        )
    if not len(updates_df):
        typer.echo("")
        typer.echo("Every question routed to a skill is already demonstrated by it.")
        return
    typer.echo("")
    typer.echo("Add to each file:")
    for row in updates_df.to_dict("records"):
        new_note = (
            f", {row['n_new_since_last_run']} new since last run"
            if row["n_new_since_last_run"]
            else ""
        )
        typer.echo("")
        typer.echo(
            f"  {row['source_file']} — {row['skill_name']} "
            f"({row['uncovered_asks']} asks, {row['n_users']} users{new_note})"
        )
        for prompt in row["new_prompts"]:
            preview = prompt.replace("\n", " ")
            if len(preview) > _PROMPT_PREVIEW_CHARS:
                preview = preview[: _PROMPT_PREVIEW_CHARS - 1] + "…"
            typer.echo(f"    + {preview}")
        if row["new_keywords"]:
            typer.echo(f"    keywords: {', '.join(row['new_keywords'])}")


def _live_client(settings: Settings) -> PhoenixClientWrapper:
    """A Phoenix client, or a clean exit explaining what is missing."""
    client = PhoenixClientWrapper(settings)
    if not client.available():
        typer.secho(
            "Phoenix is not available: set PHOENIX_COLLECTOR_ENDPOINT and install "
            "the 'live' extra (arize-phoenix-client).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    return client


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _echo_scrape(report: ScrapeReport) -> None:
    typer.echo(
        f"[{report.source}] pulled={report.pulled} inserted={report.inserted} "
        f"skipped={report.skipped}"
    )


def _echo_sync(report: AnnotationSyncReport) -> None:
    typer.echo(
        f"[annotations:{report.direction}] spans={report.spans_considered} "
        f"annotations={report.annotations} stored={report.stored} "
        f"skipped={report.skipped}"
    )


def _echo_quality(overview: dict, summary_df) -> None:
    """Print the validation scoreboard: headline pass rate then per-check failures."""
    if not overview.get("n_checks"):
        typer.echo("No spans to validate — scrape or seed first.")
        return
    pass_rate = overview.get("span_pass_rate")
    typer.echo(
        f"Validated {overview['n_evaluated_spans']} spans with {overview['n_checks']} "
        f"checks: {overview['n_failed_checks']} failed across "
        f"{overview['n_failed_spans']} spans "
        f"({'n/a' if pass_rate is None else f'{pass_rate:.1%} clean'})."
    )
    typer.echo(
        f"  {overview['n_output_issues']} output issues · "
        f"{overview['n_prompt_issues']} prompt issues · "
        f"sources: {', '.join(overview['sources']) or '-'}"
    )
    failing = summary_df[summary_df["n_failed"] > 0] if len(summary_df) else summary_df
    if not len(failing):
        typer.echo("")
        typer.echo("Every check passed.")
        return
    typer.echo("")
    header = f"{'check':<24} {'target':<8} {'failed':>7} {'rate':>7}  example"
    typer.echo(header)
    typer.echo("-" * (len(header) + 30))
    for row in failing.head(_TOP_N).to_dict("records"):
        example = str(row["example"]).replace("\n", " ")
        if len(example) > _PROMPT_PREVIEW_CHARS:
            example = example[: _PROMPT_PREVIEW_CHARS - 1] + "…"
        typer.echo(
            f"{row['check']:<24} {row['target']:<8} {row['n_failed']:>7} "
            f"{row['fail_rate']:>6.1%}  {example}"
        )


def _echo_summary(result: AnalysisResult) -> None:
    typer.echo(
        f"Analyzed {result.n_spans_analyzed} spans -> {len(result.clusters)} clusters, "
        f"{len(result.matches)} skill matches, {len(result.proposals)} gap proposals, "
        f"{len(result.sessions)} sessions."
    )
    if result.evaluations:
        failed = sum(
            1 for e in result.evaluations
            if e.score is not None and e.score < evaluations_mod.PASS_SCORE
        )
        typer.echo(
            f"Validation: {len(result.evaluations)} checks, {failed} failed "
            f"(`pheonix evaluate` for the breakdown)."
        )


def _echo_top_prompts(clusters: tuple[PromptCluster, ...], top_n: int = _TOP_N) -> None:
    typer.echo("")
    typer.echo(f"Top prompts (by frequency, top {top_n})")
    header = f"{'#':>3}  {'count':>5}  {'sessions':>8}  {'cost $':>8}  prompt"
    typer.echo(header)
    typer.echo("-" * (len(header) + _PROMPT_PREVIEW_CHARS - len("prompt")))
    ranked = sorted(clusters, key=lambda c: c.count, reverse=True)[:top_n]
    for rank, cluster in enumerate(ranked, start=1):
        preview = cluster.representative.replace("\n", " ")
        if len(preview) > _PROMPT_PREVIEW_CHARS:
            preview = preview[: _PROMPT_PREVIEW_CHARS - 1] + "…"
        typer.echo(
            f"{rank:>3}  {cluster.count:>5}  {cluster.n_sessions:>8}  "
            f"{cluster.total_cost_usd:>8.2f}  {preview}"
        )
