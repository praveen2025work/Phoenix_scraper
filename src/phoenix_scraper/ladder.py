"""Rung 1 of the promotion ladder: recurring prompt -> skill, plus the lifecycle
state machine. Pure — DataFrame / value in, value out. No store, no I/O.

`detect_rung1` turns a run's scoped analysis into `Rung1Signal`s (one per
in-scope cluster that needs a skill it does not have). `next_status` /
`advance_unobserved` / `is_material_change` are the §10.1 status machine, one
transition at a time. `ladder_run.update_rung1` (store-touching) drives them.
"""

from typing import Literal

import pandas as pd

from .config import Settings
from .models import Capability, PromptCluster, SkillMatch, _Frozen


class LadderThresholds(_Frozen):
    rung1_min_users: int
    rung1_min_count: int
    rung1_sustained_runs: int
    material_change_count_factor: float
    material_change_users_delta: int
    skill_match_threshold: float
    skill_coverage_threshold: float


def resolve_thresholds(capability: Capability, settings: Settings) -> LadderThresholds:
    """Settings defaults, overridden by capability.thresholds for the rung1_* keys."""
    over = capability.thresholds
    return LadderThresholds(
        rung1_min_users=int(over.get("rung1_min_users", settings.rung1_min_users)),
        rung1_min_count=int(over.get("rung1_min_count", settings.rung1_min_count)),
        rung1_sustained_runs=int(
            over.get("rung1_sustained_runs", settings.rung1_sustained_runs)
        ),
        material_change_count_factor=settings.material_change_count_factor,
        material_change_users_delta=settings.material_change_users_delta,
        skill_match_threshold=settings.skill_match_threshold,
        skill_coverage_threshold=settings.skill_coverage_threshold,
    )


class Rung1Signal(_Frozen):
    cluster_id: str
    subtype: Literal["new_skill", "strengthen_skill"]
    title: str
    signature: str
    matched_skill: str | None
    score: float  # gap strength, 0-1
    count: int
    n_users: int
    n_sessions: int
    total_cost_usd: float
    route_len_avg: float | None
    long_route: bool
    met_evidence_bar: bool


def _creation_floor(thresholds: LadderThresholds) -> int:
    return max(3, thresholds.rung1_min_count // 3)


def _efficiency_lookup(efficiency: pd.DataFrame) -> dict[str, tuple[float | None, bool]]:
    out: dict[str, tuple[float | None, bool]] = {}
    if efficiency is None or efficiency.empty:
        return out
    for row in efficiency.to_dict("records"):
        out[row["cluster_id"]] = (
            row.get("route_len_avg"), bool(row.get("long_route")),
        )
    return out


def _coverage_lookup(annotated: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    if annotated is None or annotated.empty:
        return out
    for row in annotated.to_dict("records"):
        out[row["cluster_id"]] = float(row.get("coverage_score") or 0.0)
    return out


def detect_rung1(
    clusters: list[PromptCluster],
    matches: list[SkillMatch],
    annotated: pd.DataFrame,
    efficiency: pd.DataFrame,
    *,
    thresholds: LadderThresholds,
) -> list[Rung1Signal]:
    """One Rung1Signal per in-scope cluster that needs a skill it does not have."""
    floor = _creation_floor(thresholds)
    match_by_cluster = {m.cluster_id: m for m in matches}
    coverage = _coverage_lookup(annotated)
    routes = _efficiency_lookup(efficiency)

    signals: list[Rung1Signal] = []
    for cluster in clusters:
        if cluster.count < floor:
            continue
        match = match_by_cluster.get(cluster.cluster_id)
        if match is None or match.score < thresholds.skill_match_threshold:
            subtype: Literal["new_skill", "strengthen_skill"] = "new_skill"
            matched_skill: str | None = None
            best = match.score if match else 0.0
            score = round(1.0 - best, 4)
        else:
            cov = coverage.get(cluster.cluster_id, 0.0)
            if cov >= thresholds.skill_coverage_threshold:
                continue  # covered: the skill works
            subtype = "strengthen_skill"
            matched_skill = match.skill_name
            gap = (
                thresholds.skill_coverage_threshold - cov
            ) / thresholds.skill_coverage_threshold
            score = round(min(1.0, max(0.0, gap)), 4)

        route_len, long_route = routes.get(cluster.cluster_id, (None, False))
        signals.append(
            Rung1Signal(
                cluster_id=cluster.cluster_id,
                subtype=subtype,
                title=cluster.representative.strip()[:200],
                signature=cluster.signature,
                matched_skill=matched_skill,
                score=score,
                count=cluster.count,
                n_users=cluster.n_users,
                n_sessions=cluster.n_sessions,
                total_cost_usd=cluster.total_cost_usd,
                route_len_avg=route_len,
                long_route=long_route,
                met_evidence_bar=(
                    cluster.n_users >= thresholds.rung1_min_users
                    and cluster.count >= thresholds.rung1_min_count
                ),
            )
        )
    return signals
