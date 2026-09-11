"""Precompute Analytics/Usage panels for one capability run.

After a capability run finishes, Usage serves these aggregates instead of
re-scanning the live corpus for every panel.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pandas as pd

from . import insights, insights_llm, insights_quality, insights_users, skill_coverage
from .capability import capability_query_filters
from .capability_skills import load_capability_skills
from .config import Settings
from .models import Capability, PromptCluster, QueryFilters, SkillEntry
from .pipeline import ANALYSIS_SPAN_LIMIT
from .skills_mapper import match_clusters
from .storage import Store

# Row ceiling for evaluation rollups — mirrors api.EVALUATION_ROW_LIMIT.
_EVALUATION_ROW_LIMIT = ANALYSIS_SPAN_LIMIT * 20

_PROPOSAL_COLUMNS = [
    "cluster_id", "proposed_name", "level", "asset_class", "capability",
    "description", "evidence_count", "representative_prompt", "sample_span_ids",
]


def records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """DataFrame → JSON-safe list of dicts (NaN → null, datetimes → ISO)."""
    if df is None or getattr(df, "empty", True):
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _overview(
    spans: pd.DataFrame, *, n_clusters: int, n_matches: int, n_proposals: int
) -> dict[str, Any]:
    if spans.empty:
        return {
            "n_spans": 0,
            "n_traces": 0,
            "n_sessions": 0,
            "n_users": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "error_rate": 0.0,
            "avg_latency_ms": None,
            "first_span": None,
            "last_span": None,
            "n_clusters": n_clusters,
            "n_matches": n_matches,
            "n_proposals": n_proposals,
        }
    errors = insights.error_mask(spans["status_code"])
    return {
        "n_spans": len(spans),
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


def _proposals_for_run(
    store: Store,
    settings: Settings,
    capability: Capability,
    run_id: str,
    skills: list[SkillEntry],
) -> pd.DataFrame:
    snap = store.capability_run_snapshot_frame(capability.id, run_id)
    if snap.empty:
        return pd.DataFrame(columns=_PROPOSAL_COLUMNS)
    members = store.capability_cluster_members_frame(capability.id, run_id)
    spans_by_cluster: dict[str, list[str]] = {}
    if not members.empty:
        for row in members.to_dict("records"):
            spans_by_cluster.setdefault(row["cluster_id"], []).append(row["span_id"])
    clusters = [
        PromptCluster(
            cluster_id=r["cluster_id"],
            signature=str(r.get("signature") or ""),
            representative=str(r.get("representative") or ""),
            count=int(r.get("count") or 0),
            n_users=int(r.get("n_users") or 0),
            asset_classes=tuple(json.loads(r.get("asset_classes") or "[]")),
            span_ids=tuple(spans_by_cluster.get(r["cluster_id"], [])),
        )
        for r in snap.to_dict("records")
    ]
    _, proposals = match_clusters(
        clusters, skills, threshold=settings.skill_match_threshold
    )
    rows = [
        {
            "cluster_id": p.cluster_id,
            "proposed_name": p.proposed_name,
            "level": p.level,
            "asset_class": p.asset_class,
            "capability": p.capability,
            "description": p.description,
            "evidence_count": p.evidence_count,
            "representative_prompt": p.representative_prompt,
            "sample_span_ids": json.dumps(list(p.sample_span_ids)),
        }
        for p in proposals
    ]
    if rows:
        return pd.DataFrame(rows, columns=_PROPOSAL_COLUMNS)
    return pd.DataFrame(columns=_PROPOSAL_COLUMNS)


def build_minimal_analytics_snapshot(
    store: Store,
    capability: Capability,
    *,
    run_id: str,
    window_start: datetime,
    window_end: datetime,
    n_clusters: int = 0,
    n_matches: int = 0,
    n_proposals: int = 0,
) -> dict[str, Any]:
    """Overview-only snapshot so Usage unlocks even when full panels fail.

    Missing panel keys are omitted so the SPA falls back to live endpoints.
    """
    filters = capability_query_filters(
        capability, start=window_start, end=window_end, limit=ANALYSIS_SPAN_LIMIT
    )
    spans = store.spans_frame(filters)
    if n_clusters == 0:
        snap = store.capability_run_snapshot_frame(capability.id, run_id)
        n_clusters = 0 if snap.empty else len(snap)
        if not snap.empty and "skill_name" in snap.columns:
            matched = snap["skill_name"].notna() & (snap["skill_name"].astype(str) != "")
            n_matches = int(matched.sum())
    return {
        "overview": _overview(
            spans,
            n_clusters=n_clusters,
            n_matches=n_matches,
            n_proposals=n_proposals,
        ),
    }


def build_analytics_snapshot(
    store: Store,
    settings: Settings,
    capability: Capability,
    *,
    run_id: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    """Compute the Analytics page panel payloads for one finished run.

    Keys match what the SPA sections expect (see Analytics.tsx / Headline /
    Coverage / Quality / Behaviour). Missing or empty panels are empty dicts/lists.
    """
    filters = capability_query_filters(
        capability, start=window_start, end=window_end, limit=ANALYSIS_SPAN_LIMIT
    )
    eval_filters = QueryFilters(
        **{
            **filters.model_dump(),
            "limit": _EVALUATION_ROW_LIMIT,
        }
    )
    spans = store.spans_frame(filters)
    skills = load_capability_skills(settings, capability)
    # annotate_coverage needs the real coverage threshold for rollups
    snap = store.capability_run_snapshot_frame(capability.id, run_id)
    if snap.empty:
        annotated = pd.DataFrame()
        clusters_df = pd.DataFrame()
        matches_df = pd.DataFrame()
    else:
        clusters_df = snap.loc[
            :, ["cluster_id", "signature", "representative", "count", "n_users",
                "first_seen", "last_seen"]
        ]
        matched = snap.loc[snap["skill_name"].notna() & (snap["skill_name"] != "")]
        matches_df = (
            matched.loc[:, ["cluster_id", "skill_name"]].assign(score=0.0)
            if not matched.empty
            else pd.DataFrame(columns=["cluster_id", "skill_name", "score"])
        )
        annotated = skill_coverage.annotate_coverage(
            clusters_df, matches_df, skills,
            threshold=settings.skill_coverage_threshold,
        )

    previous = store.previous_capability_run_id(capability.id, before=run_id)
    deltas = skill_coverage.cluster_deltas(
        snap, store.capability_run_snapshot_frame(capability.id, previous)
    )
    members = store.capability_cluster_members_frame(capability.id, run_id)
    efficiency = insights.cluster_efficiency(spans, clusters_df, members)
    proposals_df = _proposals_for_run(store, settings, capability, run_id, skills)
    n_matches = len(matches_df) if not matches_df.empty else 0
    n_proposals = len(proposals_df) if not proposals_df.empty else 0

    uncovered = skill_coverage.uncovered_queries(annotated, deltas)
    updates = skill_coverage.suggested_updates(
        uncovered, skills, max_prompts=settings.max_suggested_prompts
    )

    evaluations = store.evaluations_frame(eval_filters)

    return {
        "overview": _overview(
            spans,
            n_clusters=len(clusters_df) if not clusters_df.empty else 0,
            n_matches=n_matches,
            n_proposals=n_proposals,
        ),
        "quality_overview": insights_quality.quality_overview(evaluations),
        "activity": records(insights_users.daily_activity(spans)),
        "delta": records(deltas),
        "skills_coverage": records(skill_coverage.skill_coverage(annotated)),
        "skills_updates": records(updates),
        "skills_gaps": records(proposals_df),
        "skill_health": records(insights.skill_health(efficiency, matches_df)),
        "questions": records(insights.question_taxonomy(spans)),
        "quality_checks": records(insights_quality.quality_summary(evaluations)),
        "quality_by_user_id": records(
            insights_quality.quality_by_dimension(evaluations, "user_id")
        ),
        "quality_by_model_name": records(
            insights_quality.quality_by_dimension(evaluations, "model_name")
        ),
        "quality_by_prompt": records(
            insights_quality.quality_by_cluster(evaluations, clusters_df, members)
        ),
        "quality_failures": records(
            insights_quality.failing_spans(evaluations, limit=25)
        ),
        "flows": records(insights_llm.agent_flows(spans)),
        "efficiency": records(efficiency),
        "breakdown": records(insights_llm.stage_asset_breakdown(spans)),
        "tools": records(insights_llm.tool_usage(spans)),
        "models": records(insights_llm.model_usage(spans)),
        "users": records(insights_users.user_profiles(spans)),
    }
