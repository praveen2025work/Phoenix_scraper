"""Persist a run's Rung-1 and Rung-2 candidates: upsert `candidates`, write one
`candidate_observations` row each, run the §10.1 state machine, and advance the
lifecycle for candidates not seen this run. Store-touching companion to the pure
`ladder.py`.
"""

from datetime import datetime

from . import determinism
from .ladder import (
    LadderThresholds,
    Rung1Signal,
    advance_unobserved,
    next_status,
)
from .models import Candidate, CandidateDecision, CandidateObservation, Capability, _Frozen
from .storage import Store


class Rung1RunOutcome(_Frozen):
    n_candidates: int = 0
    n_ready: int = 0
    notes: tuple[str, ...] = ()
    crossed: tuple[str, ...] = ()


def _candidate_id(capability_id: str, cluster_id: str) -> str:
    return f"{capability_id}:s:{cluster_id}"


def _observation(
    signal: Rung1Signal, cid: str, run_id: str, observed_at: datetime, crossed: bool
) -> CandidateObservation:
    return CandidateObservation(
        candidate_id=cid,
        run_id=run_id,
        observed_at=observed_at,
        count=signal.count,
        n_users=signal.n_users,
        n_sessions=signal.n_sessions,
        total_cost_usd=signal.total_cost_usd,
        score=signal.score,
        signals={
            "subtype": signal.subtype,
            "route_len_avg": signal.route_len_avg,
            "long_route": signal.long_route,
        },
        met_evidence_bar=signal.met_evidence_bar,
        crossed_threshold=crossed,
    )


def update_rung1(
    store: Store,
    capability: Capability,
    *,
    run_id: str,
    run_ordinal: int,
    capability_run_count: int,
    observed_at: datetime,
    signals: list[Rung1Signal],
    thresholds: LadderThresholds,
    history_limit: int,
) -> Rung1RunOutcome:
    seen_ids: set[str] = set()
    n_ready = 0
    crossed_ids: list[str] = []

    for signal in signals:
        cid = _candidate_id(capability.id, signal.cluster_id)
        seen_ids.add(cid)
        existing = store.get_candidate(cid)

        prev_recent = store.recent_candidate_observations(cid, 1)
        prev_met = prev_recent[0].met_evidence_bar if prev_recent else False
        crossed = signal.met_evidence_bar and not prev_met
        if crossed:
            crossed_ids.append(cid)

        obs = _observation(signal, cid, run_id, observed_at, crossed)
        store.record_candidate_observation(obs)
        recent = store.recent_candidate_observations(cid, thresholds.rung1_sustained_runs)

        if existing is None:
            candidate = Candidate(
                candidate_id=cid,
                capability_id=capability.id,
                rung="skill",
                subtype=signal.subtype,
                cluster_id=signal.cluster_id,
                title=signal.title,
                signature=signal.signature,
                matched_skill=signal.matched_skill,
                status="new",
                first_seen_run_id=run_id,
                first_seen_at=observed_at,
                last_seen_run_id=run_id,
                last_seen_at=observed_at,
            )
        else:
            candidate = existing.model_copy(update={
                "subtype": signal.subtype,
                "matched_skill": signal.matched_skill,
                "title": signal.title,
                "signature": signal.signature,
                "last_seen_run_id": run_id,
                "last_seen_at": observed_at,
            })

        transition = next_status(
            candidate, obs, recent,
            run_ordinal=run_ordinal,
            capability_run_count=capability_run_count,
            thresholds=thresholds,
        )
        updates: dict = {
            "status": transition.status,
            "current_evidence": {
                "count": signal.count, "n_users": signal.n_users,
                "score": signal.score, "subtype": signal.subtype,
            },
        }
        if transition.set_ready_at and candidate.ready_at is None:
            updates["ready_at"] = observed_at
        store.upsert_candidate(candidate.model_copy(update=updates))

        if transition.decision_action == "reopen":
            store.record_candidate_decision(CandidateDecision(
                candidate_id=cid, run_id=run_id, action="reopen",
                actor="pheonix", note=transition.note or "material change",
                created_at=observed_at,
            ))
        if transition.status == "ready":
            n_ready += 1
        store.prune_candidate_observations(cid, history_limit)

    _advance_unobserved(
        store, capability.id, run_ordinal, seen_ids, history_limit, rung="skill"
    )

    notes: list[str] = []
    if signals:
        notes.append(
            f"Rung 1: {len(signals)} candidates observed "
            f"({n_ready} ready, {len(crossed_ids)} crossed the bar)"
        )
    return Rung1RunOutcome(
        n_candidates=len(signals),
        n_ready=n_ready,
        notes=tuple(notes),
        crossed=tuple(crossed_ids),
    )


def _advance_unobserved(
    store: Store,
    capability_id: str,
    run_ordinal: int,
    seen_ids: set[str],
    history_limit: int,
    *,
    rung: str,
) -> None:
    frame = store.candidates_frame(capability_id, rung=rung)
    for row in frame.to_dict("records"):
        cid = row["candidate_id"]
        if cid in seen_ids:
            continue
        candidate = store.get_candidate(cid)
        if candidate is None:
            continue
        last_seen_ordinal = store.capability_run_ordinal(
            capability_id, candidate.last_seen_run_id
        )
        transition = advance_unobserved(
            candidate,
            run_ordinal=run_ordinal,
            last_seen_ordinal=last_seen_ordinal,
            history_limit=history_limit,
        )
        if transition is not None and transition.status != candidate.status:
            store.upsert_candidate(
                candidate.model_copy(update={"status": transition.status})
            )


# --- Rung 2 -----------------------------------------------------------------


class Rung2RunOutcome(_Frozen):
    n_candidates: int = 0
    n_ready: int = 0
    n_insufficient: int = 0
    notes: tuple[str, ...] = ()
    crossed: tuple[str, ...] = ()


def _r2_candidate_id(capability_id: str, cluster_id: str) -> str:
    return f"{capability_id}:d:{cluster_id}"


def _r2_observation(
    signal: determinism.Rung2Signal, cid: str, run_id: str, observed_at: datetime,
    crossed: bool,
) -> CandidateObservation:
    s = signal.signals
    return CandidateObservation(
        candidate_id=cid, run_id=run_id, observed_at=observed_at,
        count=signal.n_answer_spans, n_users=0, n_sessions=0, total_cost_usd=0.0,
        score=signal.determinism_score,
        signals={
            "template_concentration": s.template_concentration,
            "route_invariance": s.route_invariance,
            "output_self_similarity": s.output_self_similarity,
            "slot_stability": s.slot_stability,
            "n_templates": s.n_templates,
            "n_answer_spans": s.n_answer_spans,
            "route_applicable": s.route_applicable,
            "templates": [list(t) for t in signal.templates],
        },
        met_evidence_bar=signal.met_evidence_bar,
        crossed_threshold=crossed,
    )


def update_rung2(
    store: Store,
    capability: Capability,
    *,
    run_id: str,
    run_ordinal: int,
    capability_run_count: int,
    observed_at: datetime,
    signals: list[determinism.Rung2Signal],
    thresholds: LadderThresholds,
    history_limit: int,
) -> Rung2RunOutcome:
    seen_ids: set[str] = set()
    n_ready = n_insufficient = recorded = 0
    crossed_ids: list[str] = []

    for signal in signals:
        cid = _r2_candidate_id(capability.id, signal.cluster_id)
        existing = store.get_candidate(cid)
        creation_ok = signal.eligible and signal.determinism_score >= 0.5
        if existing is None and not creation_ok:
            continue
        recorded += 1
        seen_ids.add(cid)

        prev = store.recent_candidate_observations(cid, 1)
        prev_met = prev[0].met_evidence_bar if prev else False
        crossed = signal.met_evidence_bar and not prev_met
        if crossed:
            crossed_ids.append(cid)

        obs = _r2_observation(signal, cid, run_id, observed_at, crossed)
        store.record_candidate_observation(obs)
        recent = store.recent_candidate_observations(cid, thresholds.rung2_sustained_runs)

        if existing is None:
            candidate = Candidate(
                candidate_id=cid, capability_id=capability.id, rung="deterministic",
                subtype="", cluster_id=signal.cluster_id, title=signal.title,
                signature=signal.signature, matched_skill=signal.matched_skill,
                status="new", first_seen_run_id=run_id, first_seen_at=observed_at,
                last_seen_run_id=run_id, last_seen_at=observed_at,
            )
        else:
            candidate = existing.model_copy(update={
                "matched_skill": signal.matched_skill, "title": signal.title,
                "signature": signal.signature, "last_seen_run_id": run_id,
                "last_seen_at": observed_at,
            })

        transition = next_status(
            candidate, obs, recent, run_ordinal=run_ordinal,
            capability_run_count=capability_run_count, thresholds=thresholds,
            eligible=signal.eligible, rung="deterministic",
        )
        updates: dict = {
            "status": transition.status,
            "current_evidence": {
                "determinism_score": signal.determinism_score,
                "n_answer_spans": signal.n_answer_spans,
                "n_templates": signal.signals.n_templates,
            },
        }
        if transition.set_ready_at and candidate.ready_at is None:
            updates["ready_at"] = observed_at
        store.upsert_candidate(candidate.model_copy(update=updates))

        if transition.decision_action == "reopen":
            store.record_candidate_decision(CandidateDecision(
                candidate_id=cid, run_id=run_id, action="reopen", actor="pheonix",
                note=transition.note or "material change", created_at=observed_at,
            ))
        if transition.status == "ready":
            n_ready += 1
        if transition.status == "insufficient_data":
            n_insufficient += 1
        store.prune_candidate_observations(cid, history_limit)

    _advance_unobserved(
        store, capability.id, run_ordinal, seen_ids, history_limit,
        rung="deterministic",
    )

    notes: list[str] = []
    skipped = sum(1 for s in signals if not s.eligible)
    if skipped:
        notes.append(f"Rung 2: {skipped} clusters skipped (no output text)")
    if recorded:
        notes.append(f"Rung 2: {recorded} candidates observed ({n_ready} ready)")
    return Rung2RunOutcome(
        n_candidates=recorded, n_ready=n_ready, n_insufficient=n_insufficient,
        notes=tuple(notes), crossed=tuple(crossed_ids),
    )
