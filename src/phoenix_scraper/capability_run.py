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

from .capability import capability_query_filters, capability_skill_dirs
from .cluster import build_clusters
from .config import Settings
from .costs import compute_span_costs, load_pricing
from .insights import cluster_efficiency
from .models import (
    Capability,
    CapabilityRun,
    CapabilityRunResult,
    SkillEntry,
)
from .pipeline import ANALYSIS_SPAN_LIMIT
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
        status="partial" if run_notes else "ok",
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
