"""Run the mining pipeline scoped to one capability, and orchestrate runs.

`run_capability_analysis` is the per-capability unit: it does NOT scrape — it
reads the already-populated store, restricts to the capability's filter + window,
runs costs -> clusters -> skills -> matches -> coverage -> efficiency, records a
`capability_runs` row plus this run's `capability_cluster_snapshots` /
`capability_cluster_members`, and returns a `CapabilityRunResult`.

`run_capabilities` is the orchestrator used by `pheonix run` and (Phase E) the
API: it syncs each `capability.yaml` into the DB, scrapes each distinct Phoenix
project once (best-effort), then loops `run_capability_analysis`, isolating
failures so one capability never aborts the others.

Rung 1 / Rung 2 candidate detection is Phase C / D — the run rows carry
`n_rung1_candidates` / `n_rung2_candidates`, written 0 here.
"""

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd

from .capability import (
    capability_query_filters,
    capability_skill_dirs,
    load_all_capabilities,
    load_capability,
)
from .cluster import build_clusters
from .config import Settings
from .costs import compute_span_costs, load_pricing
from .insights import cluster_efficiency
from .ladder import detect_rung1, detect_rung2, resolve_thresholds
from .ladder_run import update_rung1, update_rung2
from .models import (
    Capability,
    CapabilityRun,
    CapabilityRunResult,
    SkillEntry,
)
from .phoenix_client import PhoenixClientWrapper
from .pipeline import ANALYSIS_SPAN_LIMIT
from .scraper import scrape_once
from .skill_coverage import annotate_coverage
from .skills import load_all_skills, scan_skill_files
from .skills_mapper import match_clusters
from .storage import Store

logger = logging.getLogger(__name__)


def load_capability_skills(settings: Settings, capability: Capability) -> list[SkillEntry]:
    """Catalog + PHEONIX_SKILLS_DIRS + this capability's own loose ``skills/*.md``
    files, de-duped by name (earlier source wins, matching ``load_all_skills``)."""
    cap_skill_files = [
        path
        for directory in capability_skill_dirs(settings.capabilities_dir, capability.id)
        for path in sorted(directory.glob("*.md"))
    ]
    combined = load_all_skills(settings) + scan_skill_files(cap_skill_files)
    seen: set[str] = set()
    unique: list[SkillEntry] = []
    for skill in combined:
        if skill.name not in seen:
            seen.add(skill.name)
            unique.append(skill)
    return unique


def _clusters_frame(clusters: list) -> pd.DataFrame:
    if not clusters:
        return pd.DataFrame(
            columns=["cluster_id", "signature", "representative", "count", "n_users"]
        )
    return pd.DataFrame([c.model_dump() for c in clusters])


def _members_frame(clusters: list) -> pd.DataFrame:
    rows = [
        {"cluster_id": c.cluster_id, "span_id": sid}
        for c in clusters
        for sid in c.span_ids
    ]
    return pd.DataFrame(rows, columns=["cluster_id", "span_id"])


def _snapshot_rows(
    capability_id: str,
    run_id: str,
    clusters: list,
    matches: list,
    annotated: pd.DataFrame,
    efficiency: pd.DataFrame,
) -> list[dict]:
    skill_by_cluster = {m.cluster_id: m.skill_name for m in matches}
    covered_by_cluster: dict[str, int] = {}
    if not annotated.empty and "covered" in annotated.columns:
        for row in annotated.to_dict("records"):
            covered_by_cluster[row["cluster_id"]] = int(bool(row["covered"]))
    route_by_cluster: dict[str, tuple[float | None, int]] = {}
    if not efficiency.empty:
        for row in efficiency.to_dict("records"):
            route_by_cluster[row["cluster_id"]] = (
                row.get("route_len_avg"), int(bool(row.get("long_route"))),
            )
    rows = []
    for c in clusters:
        route_len, long_route = route_by_cluster.get(c.cluster_id, (None, 0))
        rows.append(
            {
                "capability_id": capability_id,
                "run_id": run_id,
                "cluster_id": c.cluster_id,
                "signature": c.signature,
                "representative": c.representative,
                "count": c.count,
                "n_users": c.n_users,
                "skill_name": skill_by_cluster.get(c.cluster_id),
                "covered": covered_by_cluster.get(c.cluster_id, 0),
                "in_scope": 1,
                "route_len_avg": route_len,
                "long_route": long_route,
                "first_seen": c.first_seen.isoformat() if c.first_seen else None,
                "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            }
        )
    return rows


def run_capability_analysis(
    store: Store,
    settings: Settings,
    capability: Capability,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    replace_today: bool = False,
    notes: list[str] | None = None,
    now: datetime | None = None,
) -> CapabilityRunResult:
    """Analyse the capability's in-scope spans over its window and record the run.

    Does not scrape. ``notes`` (e.g. a scrape failure from the orchestrator) are
    stored on the run and force ``status='partial'``.
    """
    started_at = now or datetime.now(UTC)
    window_end = window_end or started_at
    window_start = window_start or (window_end - timedelta(days=capability.window_days))
    run_notes = list(notes or [])
    scrape_partial = bool(notes)  # only scrape failures force status='partial'

    filters = capability_query_filters(
        capability, start=window_start, end=window_end, limit=ANALYSIS_SPAN_LIMIT
    )
    in_scope = store.spans_frame(filters)

    if not in_scope.empty:
        pricing, default_pricing = load_pricing(settings.pricing_path)
        new_costs = compute_span_costs(in_scope, pricing, default_pricing)
        if new_costs:
            store.update_span_costs(new_costs)
            in_scope = store.spans_frame(filters)

    clusters = build_clusters(in_scope, fuzz_threshold=settings.cluster_fuzz_threshold)
    skills = load_capability_skills(settings, capability)
    matches, proposals = match_clusters(
        clusters, skills, threshold=settings.skill_match_threshold
    )

    clusters_df = _clusters_frame(clusters)
    matches_df = pd.DataFrame(
        [m.model_dump() for m in matches],
        columns=["cluster_id", "skill_name", "score", "method"],
    )
    annotated = annotate_coverage(
        clusters_df, matches_df, skills, threshold=settings.skill_coverage_threshold
    )
    efficiency = cluster_efficiency(in_scope, clusters_df, _members_frame(clusters))

    reused_today = False
    if replace_today:
        existing = store.latest_capability_run_id_on_day(
            capability.id, window_end.date().isoformat()
        )
        run_id = existing or started_at.isoformat()
        reused_today = existing is not None
    else:
        run_id = started_at.isoformat()

    # Read the predecessor BEFORE recording. When --replace-today reused an
    # existing id, "latest" IS this run, so ask for the one strictly before it.
    previous_run_id = (
        store.previous_capability_run_id(capability.id, before=run_id)
        if reused_today
        else store.previous_capability_run_id(capability.id)
    )

    # Rung 1: detect candidates + run the lifecycle, before recording the run so
    # capability_runs.n_rung1_candidates is accurate. For a fresh run this run's
    # row is not written yet -> capability_run_ordinal(run_id) is 0 and the
    # ordinal falls back to count + 1; on --replace-today the row exists.
    existing_ordinal = store.capability_run_ordinal(capability.id, run_id)
    this_ordinal = existing_ordinal or (store.capability_run_ordinal(capability.id) + 1)
    run_count = max(this_ordinal, store.capability_run_ordinal(capability.id))

    thresholds = resolve_thresholds(capability, settings)
    rung1_signals = detect_rung1(
        list(clusters), list(matches), annotated, efficiency, thresholds=thresholds
    )
    rung1 = update_rung1(
        store, capability,
        run_id=run_id,
        run_ordinal=this_ordinal,
        capability_run_count=run_count,
        observed_at=started_at,
        signals=rung1_signals,
        thresholds=thresholds,
        history_limit=settings.run_history_limit,
    )
    run_notes.extend(rung1.notes)

    rung2_signals = detect_rung2(
        list(clusters), list(matches), in_scope, thresholds=thresholds
    )
    rung2 = update_rung2(
        store, capability,
        run_id=run_id,
        run_ordinal=this_ordinal,
        capability_run_count=run_count,
        observed_at=started_at,
        signals=rung2_signals,
        thresholds=thresholds,
        history_limit=settings.run_history_limit,
    )
    run_notes.extend(rung2.notes)

    run = CapabilityRun(
        run_id=run_id,
        capability_id=capability.id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        window_start=window_start,
        window_end=window_end,
        n_spans=store.span_count(),
        n_in_scope_spans=int(len(in_scope)),
        n_clusters=len(clusters),
        n_rung1_candidates=rung1.n_candidates,
        n_rung2_candidates=rung2.n_candidates,
        status="partial" if scrape_partial else "ok",
        notes=tuple(run_notes),
    )
    store.record_capability_run(
        run,
        _snapshot_rows(capability.id, run_id, clusters, matches, annotated, efficiency),
        [(c.cluster_id, sid) for c in clusters for sid in c.span_ids],
        history_limit=settings.run_history_limit,
    )
    return CapabilityRunResult(
        run=run,
        clusters=tuple(clusters),
        matches=tuple(matches),
        proposals=tuple(proposals),
        previous_run_id=previous_run_id,
    )


def _target_capabilities(
    settings: Settings, capability_ids: list[str] | None, all_active: bool
) -> list[Capability]:
    root = settings.capabilities_dir
    if all_active:
        return [c for c in load_all_capabilities(root) if c.status == "active"]
    if capability_ids:
        return [load_capability(root, cid) for cid in capability_ids]
    return []


def _scrape_projects(
    store: Store,
    settings: Settings,
    projects: set[str],
    client: PhoenixClientWrapper | None,
) -> dict[str, list[str]]:
    """Scrape each project once. Returns {project: [note, ...]} for problems."""
    notes: dict[str, list[str]] = {}
    if client is None or not client.available():
        for project in projects:
            notes.setdefault(project, []).append(
                "offline: Phoenix not available, analysed stored spans"
            )
        return notes
    for project in sorted(projects):
        try:
            scrape_once(store, client, settings.model_copy(update={"project": project}))
        except Exception as exc:  # noqa: BLE001 — any client/network error must not abort the run
            logger.warning("scrape failed for %s: %s", project, exc)
            notes.setdefault(project, []).append(f"scrape failed for {project}: {exc}")
    return notes


def run_capabilities(
    store: Store,
    settings: Settings,
    *,
    capability_ids: list[str] | None = None,
    all_active: bool = False,
    client: PhoenixClientWrapper | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    replace_today: bool = False,
    now: datetime | None = None,
) -> list[CapabilityRunResult]:
    """Sync -> scrape each distinct project once -> run each capability, isolating
    failures so one capability never aborts the others."""
    started_at = now or datetime.now(UTC)
    capabilities = _target_capabilities(settings, capability_ids, all_active)
    for cap in capabilities:
        store.upsert_capability(cap)

    projects = {
        (cap.filter.project or settings.project) for cap in capabilities
    }
    scrape_notes = _scrape_projects(store, settings, projects, client)

    results: list[CapabilityRunResult] = []
    for cap in capabilities:
        project = cap.filter.project or settings.project
        cap_notes = list(scrape_notes.get(project, []))
        try:
            results.append(
                run_capability_analysis(
                    store, settings, cap,
                    window_start=window_start, window_end=window_end,
                    replace_today=replace_today, notes=cap_notes, now=started_at,
                )
            )
        except Exception as exc:  # noqa: BLE001 — record the failure, keep going
            logger.exception("capability %s failed", cap.id)
            failed = CapabilityRun(
                run_id=started_at.isoformat(),
                capability_id=cap.id,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                window_start=window_start or (started_at - timedelta(days=cap.window_days)),
                window_end=window_end or started_at,
                status="failed",
                notes=(*cap_notes, f"analysis failed: {exc}"),
            )
            store.record_capability_run(
                failed, [], [], history_limit=settings.run_history_limit
            )
            results.append(CapabilityRunResult(run=failed))
    return results
