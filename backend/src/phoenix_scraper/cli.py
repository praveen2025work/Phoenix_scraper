"""Typer CLI: demo, seed, scrape, ingest, analyze, report, export, serve, doctor."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import typer

from . import annotations as annotations_mod
from . import artifacts as artifacts_mod
from . import capability as capability_mod
from . import capability_run as capability_run_mod
from . import evaluations as evaluations_mod
from . import export as export_mod
from . import fixtures, insights_quality, pipeline, scraper, skill_coverage
from . import ladder as ladder_mod
from . import skills as skills_mod
from .config import Settings, load_settings
from .models import (
    AnalysisResult,
    AnnotationSyncReport,
    CapabilityFilter,
    CapabilityRunResult,
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
    """Surface this package's logs (Phoenix calls, scrape counts, TLS trust)."""
    from .logging_setup import configure_logging

    # Via Settings, not os.environ: pydantic-settings reads backend/.env itself and
    # never exports into the process environment, so an os.environ lookup here would
    # silently ignore PHEONIX_LOG_LEVEL set in .env.
    configure_logging(load_settings().log_level)


capability_app = typer.Typer(
    name="capability",
    help="Create, inspect, and sync capability workspaces.",
    no_args_is_help=True,
)
app.add_typer(capability_app, name="capability")

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
    "the full project history. Ignored once a watermark exists (use --reset).",
)
ScrapeResetOpt = typer.Option(
    False,
    "--reset",
    help="Forget the watermark first, so --since (or full history) applies again — "
    "use this to backfill older spans. Re-inserts are no-ops (span_id key).",
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
CapabilitiesDirOpt = typer.Option(
    None, "--capabilities-dir", help="Override the capabilities root directory."
)
CapIdArg = typer.Argument(..., help="Capability id (kebab-case, e.g. fobo).")
CapIdOptionalArg = typer.Argument(
    None, help="One capability id; omit to act on all of them."
)
CapNameOpt = typer.Option("", "--name", help="Display name.")
CapDescriptionOpt = typer.Option("", "--description", help="One-line description.")
CapWindowDaysOpt = typer.Option(30, "--window-days", help="Default from/to span in days.")
RunCapabilityOpt = typer.Option(None, "--capability", help="Run one capability by id.")
RunAllOpt = typer.Option(False, "--all", help="Run every active capability.")
RunFromOpt = typer.Option(None, "--from", help="Window start (UTC); default now - window_days.")
RunToOpt = typer.Option(None, "--to", help="Window end (UTC); default now.")
RunDaysOpt = typer.Option(
    None, "--days", help="Window = the last N days (shortcut for --from; ignored if --from given)."
)
ReplaceTodayOpt = typer.Option(
    False, "--replace-today", help="Reuse today's run_id instead of adding a new run."
)
CandidateRungOpt = typer.Option(None, "--rung", help="skill | deterministic")
CandidateStatusOpt = typer.Option(None, "--status", help="Filter to one status.")
CandidateAllOpt = typer.Option(False, "--all", help="Include rejected + snoozed + stale.")
DecisionActionOpt = typer.Option(..., "--action", help="accept | reject | snooze | reopen")
ActorOpt = typer.Option(None, "--actor", help="Who is deciding (default: PHEONIX_OPERATOR_NAME).")
DecisionNoteOpt = typer.Option("", "--note", help="Why.")
SnoozeRunsOpt = typer.Option(3, "--snooze-runs", help="Runs to snooze for.")
PromoteAcceptOpt = typer.Option(False, "--accept", help="Allow ready -> promoted in one step.")
DryRunOpt = typer.Option(False, "--dry-run", help="Render without writing.")
CandidateIdArg = typer.Argument(..., help="Candidate id, e.g. fobo:s:abc123.")


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
    reset: bool = ScrapeResetOpt,
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
        if reset and store.clear_watermark(f"phoenix:{settings.project}"):
            typer.echo(f"watermark cleared for '{settings.project}'")
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
        report = scraper.ingest_jsonl(
            store, path, project,
            stage_keys=settings.stage_attr_keys(),
            asset_keys=settings.asset_attr_keys(),
        )
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


AttrsLimitOpt = typer.Option(40, "--limit", help="Most common keys to show.")


@app.command()
def attrs(
    limit: int = AttrsLimitOpt,
    db: Path | None = DbOpt,
) -> None:
    """List the attribute keys your stored spans actually carry.

    Use it to find where your agent puts the workflow stage / asset class, then
    point PHEONIX_STAGE_ATTR / PHEONIX_ASSET_ATTR at it (or fix the emitter).
    """
    from collections import Counter

    from .scraper import ASSET_KEYS, STAGE_KEYS, _flatten_keys

    settings = _settings(db=db)
    with _open_store(settings) as store:
        frame = store.spans_frame(QueryFilters(limit=100_000))
    if not len(frame):
        typer.echo("No spans stored yet — run `pheonix scrape` or `pheonix demo` first.")
        return

    counts: Counter[str] = Counter()
    samples: dict[str, str] = {}
    for raw in frame["attributes"].dropna():
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key, value in _flatten_keys(data).items():
            if isinstance(value, dict):
                continue  # the container itself, not a leaf
            counts[key] += 1
            samples.setdefault(key, str(value)[:40])

    if not counts:
        typer.echo("Stored spans carry no attributes.")
        return

    stage_hits = int(frame["workflow_stage"].notna().sum())
    asset_hits = int(frame["asset_class"].notna().sum())
    total = len(frame)
    typer.echo(f"{total} spans stored")
    typer.echo(f"  workflow_stage resolved on {stage_hits}/{total}")
    typer.echo(f"  asset_class    resolved on {asset_hits}/{total}")
    if not stage_hits:
        typer.secho(
            "  none of the keys below matched " + ", ".join(STAGE_KEYS[:4]) + ", …\n"
            "  set PHEONIX_STAGE_ATTR=<key from the list> if you see yours here.",
            fg=typer.colors.YELLOW,
        )
    typer.echo()
    typer.echo(f"{'attribute key':<52} {'spans':>7}  sample")
    typer.echo("-" * 96)
    known = set(STAGE_KEYS) | set(ASSET_KEYS)
    for key, n in counts.most_common(limit):
        mark = " *" if key in known else "  "
        typer.echo(f"{key:<50}{mark} {n:>7}  {samples.get(key, '')}")
    typer.echo("\n* = a key the scraper already checks for stage/asset class")


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
    uvicorn.run(create_app(settings, run_jobs=True, dev_cors=True), host=host, port=port)


UiDistOpt = typer.Option(None, "--dist", help="Path to the built SPA (default: frontend/dist).")
UiPortOpt = typer.Option(5173, "--port")


@app.command("serve-ui")
def serve_ui(
    host: str = HostOpt,
    port: int = UiPortOpt,
    dist: Path | None = UiDistOpt,
) -> None:
    """Serve the built frontend (frontend/dist) as static files with SPA fallback."""
    import http.server
    import socketserver

    root = (dist or Path("frontend/dist")).resolve()
    if not (root / "index.html").is_file():
        typer.secho(
            f"No built SPA at {root} — run `make ui-build` first.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: object, **kw: object) -> None:
            super().__init__(*a, directory=str(root), **kw)  # type: ignore[arg-type]

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def do_GET(self) -> None:
            target = (root / self.path.lstrip("/").split("?")[0]).resolve()
            in_root = str(target).startswith(str(root))
            if self.path != "/" and not (in_root and target.is_file()):
                self.path = "/index.html"
            super().do_GET()

    with socketserver.TCPServer((host, port), _Handler) as httpd:
        typer.echo(f"Serving {root} on http://{host}:{port}")
        httpd.serve_forever()


@app.command()
def run(
    capability: str | None = RunCapabilityOpt,
    run_all: bool = RunAllOpt,
    from_: datetime | None = RunFromOpt,
    to: datetime | None = RunToOpt,
    days: int | None = RunDaysOpt,
    replace_today: bool = ReplaceTodayOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Scrape + scoped-analyse one capability (or --all) over a [from, to] window."""
    if bool(capability) == bool(run_all):
        typer.secho("Pass exactly one of --capability <id> or --all.",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if days is not None and from_ is None:
        if days <= 0:
            typer.secho("--days must be a positive integer.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        from_ = datetime.now(UTC) - timedelta(days=days)
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    client = PhoenixClientWrapper(settings)
    with _open_store(settings) as store:
        try:
            results = capability_run_mod.run_capabilities(
                store, settings,
                capability_ids=[capability] if capability else None,
                all_active=run_all,
                client=client if client.available() else None,
                window_start=_utc(from_),
                window_end=_utc(to),
                replace_today=replace_today,
            )
        except (ValueError, FileNotFoundError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        if not results:
            typer.echo("No active capabilities to run.")
            return
        for result in results:
            _echo_capability_run(store, result)


def _echo_capability_run(store: Store, result: CapabilityRunResult) -> None:
    r = result.run
    typer.echo("")
    typer.echo(
        f"[{r.capability_id}] {r.run_id}  "
        f"window {r.window_start:%Y-%m-%d}..{r.window_end:%Y-%m-%d}  ·  "
        f"{r.n_spans} spans, {r.n_in_scope_spans} in scope -> "
        f"{r.n_clusters} clusters  ·  {r.status}"
    )
    for note in r.notes:
        typer.echo(f"  note: {note}")
    deltas = skill_coverage.cluster_deltas(
        store.capability_run_snapshot_frame(r.capability_id, r.run_id),
        store.capability_run_snapshot_frame(r.capability_id, result.previous_run_id),
    )
    typer.echo("  what changed since the last run:")
    if len(deltas):
        for row in deltas.head(_TOP_N).to_dict("records"):
            preview = str(row["representative"]).replace("\n", " ")[:_PROMPT_PREVIEW_CHARS]
            typer.echo(
                f"    {row['status']:<9} {row['count_prev']:>4} -> {row['count']:<4} "
                f"({row['count_change']:+d})  {preview}"
            )
    elif result.previous_run_id:
        typer.echo("    no movement")
    else:
        typer.echo("    (no earlier run to compare against)")


_HIDDEN_BY_DEFAULT = frozenset({"rejected", "snoozed", "stale"})
_DECISION_TRANSITIONS = ladder_mod.DECISION_TRANSITIONS


@app.command()
def candidates(
    cap_id: str = CapIdArg,
    rung: str | None = CandidateRungOpt,
    status: str | None = CandidateStatusOpt,
    show_all: bool = CandidateAllOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """The ladder board for a capability: candidates grouped by status."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        frame = store.candidates_frame(cap_id, rung=rung, status=status)
    if not len(frame):
        typer.echo(f"No candidates for '{cap_id}'.")
        return
    rows = frame.to_dict("records")
    if status is None and not show_all:
        rows = [r for r in rows if r["status"] not in _HIDDEN_BY_DEFAULT]
    if not rows:
        typer.echo("No active candidates (rejected/snoozed/stale hidden — use --all).")
        return
    by_status: dict[str, list[dict]] = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)
    for st, group in by_status.items():
        typer.echo(f"\n{st.upper()}  ({len(group)})")
        for r in group:
            ev = json.loads(r["current_evidence_json"] or "{}")
            typer.echo(
                f"  {r['candidate_id']:<28} {r['subtype']:<16} "
                f"{ev.get('count', 0):>4} asks / {ev.get('n_users', 0)} users  "
                f"{str(r['title'])[:60]}"
            )


@app.command()
def candidate(
    candidate_id: str = CandidateIdArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """One candidate's evidence trend, signals, and decision log."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        c = store.get_candidate(candidate_id)
        if c is None:
            typer.secho(f"No candidate {candidate_id!r}.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        obs = store.candidate_observations_frame(candidate_id)
        decisions = store.candidate_decisions_frame(candidate_id)
    typer.echo(
        f"{c.candidate_id}\n  rung={c.rung} subtype={c.subtype or '-'} "
        f"status={c.status} matched_skill={c.matched_skill or '-'}"
    )
    typer.echo(f"  title: {c.title}")
    if c.current_evidence:
        typer.echo(f"  evidence: {c.current_evidence}")
    typer.echo("\n  trend:")
    for row in obs.to_dict("records"):
        score = row["score"]
        score_s = f"{score:.2f}" if score is not None else "-"
        typer.echo(
            f"    {row['run_id']:<27} count={row['count']:<4} score={score_s:<5} "
            f"{'met' if row['met_evidence_bar'] else '   '}"
        )
    if len(obs) and c.rung == "deterministic":
        last = json.loads(obs.iloc[-1]["signals_json"] or "{}")
        typer.echo("\n  signals (latest run):")
        for key in ("template_concentration", "route_invariance",
                    "output_self_similarity", "slot_stability"):
            typer.echo(f"    {key:<24} {last.get(key)}")
        for rep, n in last.get("templates", []):
            typer.echo(f"    template ({n})  {str(rep)[:70]}")
    typer.echo("\n  decisions:")
    for row in decisions.to_dict("records"):
        typer.echo(
            f"    {row['created_at']}  {row['action']:<8} by {row['actor']}  {row['note']}"
        )
    if not len(decisions):
        typer.echo("    (none)")


@app.command()
def decide(
    candidate_id: str = CandidateIdArg,
    action: str = DecisionActionOpt,
    actor: str | None = ActorOpt,
    note: str = DecisionNoteOpt,
    snooze_runs: int = SnoozeRunsOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Record a human decision on a candidate and apply the transition."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    who = actor or settings.operator_name or "unknown"
    if action not in _DECISION_TRANSITIONS:
        typer.secho(f"Unknown action {action!r}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    allowed, target = _DECISION_TRANSITIONS[action]
    now = datetime.now(UTC)
    with _open_store(settings) as store:
        candidate = store.get_candidate(candidate_id)
        if candidate is None:
            typer.secho(f"No candidate {candidate_id!r}.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if candidate.status not in allowed:
            typer.secho(
                f"Cannot {action} a candidate in status {candidate.status!r} "
                f"(allowed from: {', '.join(sorted(allowed))}).",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(code=1)
        store.record_candidate_decision_now(candidate_id, action, who, now, note=note)
        updates: dict = {"status": target, "decided_by": who, "decided_at": now}
        if action == "reject":
            updates["dismiss_reason"] = note
            updates["current_evidence"] = {
                **candidate.current_evidence,
                "count_at_rejection": candidate.current_evidence.get("count", 0),
                "n_users_at_rejection": candidate.current_evidence.get("n_users", 0),
            }
        if action == "snooze":
            ordinal = store.capability_run_ordinal(candidate.capability_id)
            updates["snooze_until_run"] = ordinal + snooze_runs
        store.upsert_candidate(candidate.model_copy(update=updates))
    typer.echo(f"{candidate_id}: {candidate.status} -> {target}  (by {who})")


@app.command()
def promote(
    candidate_id: str = CandidateIdArg,
    accept: bool = PromoteAcceptOpt,
    actor: str | None = ActorOpt,
    dry_run: bool = DryRunOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Write the draft artifact for an accepted (or --accept a ready) candidate."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    who = actor or settings.operator_name or "unknown"
    now = datetime.now(UTC)
    with _open_store(settings) as store:
        candidate = store.get_candidate(candidate_id)
        if candidate is None:
            typer.secho(f"No candidate {candidate_id!r}.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if candidate.status == "ready" and accept and not dry_run:
            candidate = candidate.model_copy(update={"status": "accepted"})
            store.upsert_candidate(candidate)
        if candidate.status != "accepted" and not dry_run:
            typer.secho(
                f"Candidate is {candidate.status!r}; accept it first "
                f"(or pass --accept for a ready candidate).",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(code=1)
        try:
            cap = capability_mod.load_capability(
                settings.capabilities_dir, candidate.capability_id
            )
        except (ValueError, FileNotFoundError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        result = artifacts_mod.promote_candidate(
            store, cap, candidate, now=now, actor=who, settings=settings, dry_run=dry_run,
        )
    for path, body in result.contents:
        typer.echo(f"\n--- {path} ---")
        typer.echo(body)
    typer.echo("" if dry_run else f"\nWrote {len(result.paths)} artifact(s).")


@capability_app.command("new")
def capability_new(
    cap_id: str = CapIdArg,
    name: str = CapNameOpt,
    description: str = CapDescriptionOpt,
    project: str | None = ProjectOpt,
    stage: str | None = StageOpt,
    asset_class: str | None = AssetClassOpt,
    search: str | None = SearchOpt,
    window_days: int = CapWindowDaysOpt,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Scaffold capabilities/<id>/ and mirror it into the database."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    try:
        cap = capability_mod.scaffold_capability(
            settings.capabilities_dir,
            cap_id,
            name=name,
            description=description,
            cap_filter=CapabilityFilter(
                project=project,
                workflow_stage=stage,
                asset_class=asset_class,
                search=search,
            ),
            window_days=window_days,
        )
    except (ValueError, FileExistsError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    with _open_store(settings) as store:
        store.upsert_capability(cap)
    typer.echo(
        f"Created capability '{cap.id}' -> "
        f"{capability_mod.config_path(settings.capabilities_dir, cap.id)}"
    )


@capability_app.command("sync")
def capability_sync(
    cap_id: str | None = CapIdOptionalArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Re-read capability.yaml from disk into the capabilities table."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    root = settings.capabilities_dir
    if cap_id is not None:
        try:
            caps = [capability_mod.load_capability(root, cap_id)]
        except (ValueError, FileNotFoundError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
    else:
        caps = capability_mod.load_all_capabilities(root)
    if not caps:
        typer.echo("No capabilities found.")
        return
    with _open_store(settings) as store:
        for cap in caps:
            store.upsert_capability(cap)
            typer.echo(f"synced {cap.id} (status={cap.status})")


@capability_app.command("list")
def capability_list(
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """List capability workspaces on disk and whether each is synced to the DB."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    ids = capability_mod.list_capability_ids(settings.capabilities_dir)
    if not ids:
        typer.echo("No capabilities found.")
        return
    with _open_store(settings) as store:
        synced = {
            row["capability_id"]: row["status"]
            for row in store.capabilities_frame().to_dict("records")
        }
    typer.echo(f"{'id':<24} {'status':<10} synced")
    typer.echo("-" * 46)
    for cap_id in ids:
        status = synced.get(cap_id, "-")
        mark = "yes" if cap_id in synced else "not synced"
        typer.echo(f"{cap_id:<24} {status:<10} {mark}")


def _format_filter(f: CapabilityFilter) -> str:
    parts = [
        f"{label}={value}"
        for label, value in (
            ("project", f.project),
            ("stage", f.workflow_stage),
            ("asset_class", f.asset_class),
            ("model", f.model_name),
            ("search", f.search),
        )
        if value
    ]
    return ", ".join(parts) if parts else "(none — all spans)"


@capability_app.command("show")
def capability_show(
    cap_id: str = CapIdArg,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Print a capability's parsed fields and its file counts."""
    settings = _settings(capabilities_dir=capabilities_dir)
    root = settings.capabilities_dir
    try:
        cap = capability_mod.load_capability(root, cap_id)
    except (ValueError, FileNotFoundError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    cap_dir = capability_mod.capability_dir(root, cap_id)
    skills_dir, det_dir = cap_dir / "skills", cap_dir / "deterministic"
    n_skills = len(list(skills_dir.glob("*.md"))) if skills_dir.is_dir() else 0
    n_det = len(list(det_dir.glob("*.py"))) if det_dir.is_dir() else 0
    typer.echo(f"id:          {cap.id}")
    typer.echo(f"name:        {cap.name}")
    typer.echo(f"description: {cap.description or '-'}")
    typer.echo(f"status:      {cap.status}")
    typer.echo(f"window_days: {cap.window_days}")
    typer.echo(f"filter:      {_format_filter(cap.filter)}")
    if cap.thresholds:
        typer.echo(f"thresholds:  {cap.thresholds}")
    typer.echo(f"files:       skills: {n_skills}, deterministic: {n_det}")


@capability_app.command("runs")
def capability_runs(
    cap_id: str = CapIdArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Recorded runs for a capability, newest first."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        frame = store.capability_runs_frame(cap_id)
    if not len(frame):
        typer.echo(f"No runs recorded for '{cap_id}'. Run `pheonix run --capability {cap_id}`.")
        return
    typer.echo(f"{'run_id':<27} {'window':<25} {'in scope':>9} {'clusters':>9}  status")
    typer.echo("-" * 90)
    for row in frame.to_dict("records"):
        window = f"{row['window_start'][:10]}..{row['window_end'][:10]}"
        typer.echo(
            f"{row['run_id']:<27} {window:<25} {row['n_in_scope_spans']:>9} "
            f"{row['n_clusters']:>9}  {row['status']}"
        )


@capability_app.command("jobs")
def capability_jobs(
    cap_id: str = CapIdArg,
    db: Path | None = DbOpt,
    capabilities_dir: Path | None = CapabilitiesDirOpt,
) -> None:
    """Background run jobs for a capability, newest first."""
    settings = _settings(db=db, capabilities_dir=capabilities_dir)
    with _open_store(settings) as store:
        frame = store.capability_jobs_frame(cap_id)
    if not len(frame):
        typer.echo(f"No jobs for '{cap_id}'.")
        return
    typer.echo(f"{'job_id':<34} {'state':<9} {'run_id':<27} enqueued")
    typer.echo("-" * 90)
    for row in frame.to_dict("records"):
        run_id = str(row["run_id"] or "-")
        typer.echo(
            f"{row['job_id']:<34} {row['state']:<9} {run_id:<27} "
            f"{row['enqueued_at'][:19]}"
        )


# ---- helpers -------------------------------------------------------------------


def _settings(
    db: Path | None = None,
    export_dir: Path | None = None,
    project: str | None = None,
    capabilities_dir: Path | None = None,
) -> Settings:
    base = load_settings()
    updates: dict[str, object] = {
        key: value
        for key, value in (
            ("db_path", db),
            ("export_dir", export_dir),
            ("project", project),
            ("capabilities_dir", capabilities_dir),
        )
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
