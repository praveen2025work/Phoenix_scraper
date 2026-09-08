"""Rung 1 of the promotion ladder: recurring prompt -> skill, plus the lifecycle
state machine. Pure — DataFrame / value in, value out. No store, no I/O.

`detect_rung1` turns a run's scoped analysis into `Rung1Signal`s (one per
in-scope cluster that needs a skill it does not have). `next_status` /
`advance_unobserved` / `is_material_change` are the §10.1 status machine, one
transition at a time. `ladder_run.update_rung1` (store-touching) drives them.
"""

from typing import Literal

import pandas as pd

from . import determinism
from .config import Settings
from .models import (
    Candidate,
    CandidateObservation,
    CandidateStatus,
    Capability,
    PromptCluster,
    SkillMatch,
    _Frozen,
)


class LadderThresholds(_Frozen):
    rung1_min_users: int
    rung1_min_count: int
    rung1_sustained_runs: int
    material_change_count_factor: float
    material_change_users_delta: int
    skill_match_threshold: float
    skill_coverage_threshold: float
    rung2_min_answer_spans: int
    rung2_determinism_score: float
    rung2_sustained_runs: int
    cluster_fuzz_threshold: int


def resolve_thresholds(capability: Capability, settings: Settings) -> LadderThresholds:
    """Settings defaults, overridden by capability.thresholds for the rung1/2_* keys."""
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
        rung2_min_answer_spans=int(
            over.get("rung2_min_answer_spans", settings.rung2_min_answer_spans)
        ),
        rung2_determinism_score=float(
            over.get("rung2_determinism_score", settings.rung2_determinism_score)
        ),
        rung2_sustained_runs=int(
            over.get("rung2_sustained_runs", settings.rung2_sustained_runs)
        ),
        cluster_fuzz_threshold=settings.cluster_fuzz_threshold,
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


def detect_rung2(
    clusters: list[PromptCluster],
    matches: list[SkillMatch],
    in_scope: pd.DataFrame,
    *,
    thresholds: LadderThresholds,
) -> list[determinism.Rung2Signal]:
    """One Rung2Signal per cluster (eligibility + determinism_score + met bar)."""
    match_by_cluster = {m.cluster_id: m.skill_name for m in matches}
    has_span_id = not in_scope.empty and "span_id" in in_scope.columns
    signals: list[determinism.Rung2Signal] = []
    for cluster in clusters:
        members = (
            in_scope[in_scope["span_id"].isin(set(cluster.span_ids))]
            if has_span_id
            else in_scope
        )
        sig = determinism.score_cluster(
            cluster.cluster_id,
            cluster.representative.strip()[:200],
            cluster.signature,
            match_by_cluster.get(cluster.cluster_id),
            members,
            min_answer_spans=thresholds.rung2_min_answer_spans,
            fuzz_threshold=thresholds.cluster_fuzz_threshold,
        )
        met = sig.eligible and sig.determinism_score >= thresholds.rung2_determinism_score
        signals.append(sig.model_copy(update={"met_evidence_bar": met}))
    return signals


# --- §10.1 lifecycle state machine -------------------------------------------

_STALE_ELIGIBLE = frozenset({"new", "accumulating", "ready"})
_HUMAN_TERMINAL = frozenset({"accepted", "promoted"})

# §10.3 human-decision transitions: action -> (allowed-from statuses, new status).
# Shared by the CLI (`pheonix decide`) and the API (`POST /candidates/{cid}/decision`).
DECISION_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "accept": (frozenset({"ready"}), "accepted"),
    "reject": (frozenset({"accumulating", "ready", "new"}), "rejected"),
    "snooze": (frozenset({"accumulating", "ready", "new"}), "snoozed"),
    "reopen": (frozenset({"rejected", "snoozed", "stale"}), "accumulating"),
}


class LadderTransition(_Frozen):
    status: CandidateStatus
    note: str | None = None
    set_ready_at: bool = False
    decision_action: str | None = None  # "reopen" for an auto-reopen


def readiness_met(
    recent_observations: list[CandidateObservation],
    *,
    sustained_runs: int,
    capability_run_count: int,
) -> bool:
    if capability_run_count < sustained_runs:
        return False
    window = recent_observations[:sustained_runs]
    return len(window) >= sustained_runs and all(o.met_evidence_bar for o in window)


def is_material_change(
    candidate: Candidate,
    observation: CandidateObservation,
    *,
    thresholds: LadderThresholds,
) -> bool:
    ev = candidate.current_evidence
    count_at = ev.get("count_at_rejection")
    users_at = ev.get("n_users_at_rejection")
    if count_at is None or users_at is None:
        return False
    return (
        observation.count >= thresholds.material_change_count_factor * float(count_at)
        or observation.n_users >= int(users_at) + thresholds.material_change_users_delta
    )


def _unsnoozed(candidate: Candidate, run_ordinal: int) -> bool:
    return (
        candidate.status == "snoozed"
        and candidate.snooze_until_run is not None
        and run_ordinal >= candidate.snooze_until_run
    )


def next_status(
    candidate: Candidate,
    observation: CandidateObservation,
    recent_observations: list[CandidateObservation],
    *,
    run_ordinal: int,
    capability_run_count: int,
    thresholds: LadderThresholds,
    eligible: bool = True,
    rung: str = "skill",
) -> LadderTransition:
    """The transition when the candidate WAS observed this run.

    ``recent_observations`` is newest-first and INCLUDES this run's observation.
    ``eligible`` is Rung-2's ``n_answer_spans >= rung2_min_answer_spans`` gate;
    Rung 1 leaves it at the default True. ``rung`` selects the sustained-runs
    threshold (Rung 1: 5, Rung 2: 3 by default).
    """
    status = candidate.status

    if status == "snoozed":
        if _unsnoozed(candidate, run_ordinal):
            status = "accumulating"
        else:
            return LadderTransition(status="snoozed")

    if status == "rejected":
        if is_material_change(candidate, observation, thresholds=thresholds):
            return LadderTransition(
                status="accumulating",
                note=(
                    f"reopened: material change "
                    f"({observation.count} asks, {observation.n_users} users)"
                ),
                decision_action="reopen",
            )
        return LadderTransition(status="rejected")

    if status in _HUMAN_TERMINAL:
        return LadderTransition(status=status)

    if not eligible:
        if status in ("new", "accumulating", "insufficient_data", "stale"):
            return LadderTransition(status="insufficient_data")
        # a `ready` candidate that lost its answer spans falls through to the
        # readiness-fade path below.
    if status == "insufficient_data":
        status = "accumulating"

    if status == "stale":
        status = "accumulating"

    if status == "new":
        status = "accumulating" if len(recent_observations) >= 2 else "new"

    sustained = (
        thresholds.rung2_sustained_runs
        if rung == "deterministic"
        else thresholds.rung1_sustained_runs
    )
    ready = readiness_met(
        recent_observations,
        sustained_runs=sustained,
        capability_run_count=capability_run_count,
    )
    if status == "accumulating" and ready:
        return LadderTransition(status="ready", set_ready_at=True)
    if status == "ready" and not ready:
        return LadderTransition(
            status="accumulating", note="evidence fell below the bar this run"
        )
    return LadderTransition(status=status)


def advance_unobserved(
    candidate: Candidate,
    *,
    run_ordinal: int,
    last_seen_ordinal: int,
    history_limit: int,
) -> LadderTransition | None:
    """The transition when the candidate was NOT observed this run (auto-unsnooze,
    ``stale``). ``None`` = no change."""
    if _unsnoozed(candidate, run_ordinal):
        return LadderTransition(status="accumulating", note="snooze expired")
    if (
        candidate.status in _STALE_ELIGIBLE
        and run_ordinal - last_seen_ordinal >= history_limit
    ):
        return LadderTransition(
            status="stale", note=f"not seen for {history_limit} runs"
        )
    return None
