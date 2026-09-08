"""Pure-function tests for ladder threshold resolution + Rung-1 detection."""

import pandas as pd

from phoenix_scraper import ladder
from phoenix_scraper.config import Settings
from phoenix_scraper.models import Capability, CapabilityFilter, PromptCluster, SkillMatch


def _settings(**over) -> Settings:
    return Settings(db_path="x.db", **over)


def _capability(thresholds=None) -> Capability:
    return Capability(
        id="fobo", name="FOBO", filter=CapabilityFilter(workflow_stage="fobo_recon"),
        thresholds=thresholds or {},
    )


def _cluster(cid: str, count: int, n_users: int = 5, **over) -> PromptCluster:
    base = dict(
        cluster_id=cid, signature=f"sig {cid}", representative=f"why {cid} break",
        count=count, n_users=n_users, n_sessions=count, total_cost_usd=1.0,
        span_ids=tuple(f"{cid}-{i}" for i in range(count)),
    )
    base.update(over)
    return PromptCluster(**base)


class TestResolveThresholds:
    def test_settings_defaults(self) -> None:
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert t.rung1_min_users == 3 and t.rung1_min_count == 15
        assert t.rung1_sustained_runs == 5
        assert t.skill_match_threshold == 0.55 and t.skill_coverage_threshold == 0.70

    def test_capability_overrides_win(self) -> None:
        t = ladder.resolve_thresholds(
            _capability({"rung1_min_users": 8, "rung1_sustained_runs": 2}), _settings()
        )
        assert t.rung1_min_users == 8 and t.rung1_sustained_runs == 2
        assert t.rung1_min_count == 15  # untouched key still from settings

    def test_settings_env_overrides_default(self) -> None:
        t = ladder.resolve_thresholds(_capability(), _settings(rung1_min_count=40))
        assert t.rung1_min_count == 40


class TestDetectRung1:
    def _frames(self, clusters, matches, covered_ids=()):
        annotated = pd.DataFrame(
            [
                {
                    "cluster_id": m.cluster_id, "skill_name": m.skill_name,
                    "representative": "", "signature": "", "count": 0, "n_users": 0,
                    "coverage_score": 0.9 if m.cluster_id in covered_ids else 0.2,
                    "covered": m.cluster_id in covered_ids,
                }
                for m in matches
            ],
            columns=["cluster_id", "skill_name", "representative", "signature",
                     "count", "n_users", "coverage_score", "covered"],
        )
        efficiency = pd.DataFrame(
            [{"cluster_id": c.cluster_id, "route_len_avg": 3.0, "long_route": False}
             for c in clusters],
            columns=["cluster_id", "route_len_avg", "long_route"],
        )
        return annotated, efficiency

    def test_new_skill_signal_when_nothing_matches(self) -> None:
        clusters = [_cluster("aaa", count=20)]
        annotated, efficiency = self._frames(clusters, [])
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung1(clusters, [], annotated, efficiency, thresholds=t)
        assert len(signals) == 1
        s = signals[0]
        assert s.subtype == "new_skill" and s.matched_skill is None
        assert s.score == 1.0  # nothing close
        assert s.met_evidence_bar is True  # 20 >= 15, 5 >= 3

    def test_strengthen_signal_when_match_but_thin_coverage(self) -> None:
        clusters = [_cluster("bbb", count=18)]
        matches = [SkillMatch(cluster_id="bbb", skill_name="fobo-triage", score=0.72)]
        annotated, efficiency = self._frames(clusters, matches, covered_ids=())
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung1(clusters, matches, annotated, efficiency, thresholds=t)
        assert len(signals) == 1
        assert signals[0].subtype == "strengthen_skill"
        assert signals[0].matched_skill == "fobo-triage"
        assert 0 < signals[0].score <= 1

    def test_covered_cluster_yields_no_signal(self) -> None:
        clusters = [_cluster("ccc", count=30)]
        matches = [SkillMatch(cluster_id="ccc", skill_name="fobo-triage", score=0.9)]
        annotated, efficiency = self._frames(clusters, matches, covered_ids={"ccc"})
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert ladder.detect_rung1(clusters, matches, annotated, efficiency, thresholds=t) == []

    def test_below_creation_floor_yields_no_signal(self) -> None:
        # floor = max(3, 15 // 3) = 5
        clusters = [_cluster("ddd", count=4)]
        annotated, efficiency = self._frames(clusters, [])
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert ladder.detect_rung1(clusters, [], annotated, efficiency, thresholds=t) == []

    def test_between_floor_and_bar_is_signal_but_bar_not_met(self) -> None:
        clusters = [_cluster("eee", count=8, n_users=2)]
        annotated, efficiency = self._frames(clusters, [])
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung1(clusters, [], annotated, efficiency, thresholds=t)
        assert len(signals) == 1 and signals[0].met_evidence_bar is False


from datetime import UTC, datetime  # noqa: E402

from phoenix_scraper.models import Candidate, CandidateObservation  # noqa: E402

_TS = datetime(2026, 9, 7, tzinfo=UTC)


def _cand2(status: str = "new", **over) -> Candidate:
    base = dict(
        candidate_id="fobo:s:aaa", capability_id="fobo", rung="skill",
        subtype="new_skill", cluster_id="aaa", title="t", signature="s",
        first_seen_run_id="r1", first_seen_at=_TS, last_seen_run_id="r1",
        last_seen_at=_TS, status=status,
    )
    base.update(over)
    return Candidate(**base)


def _o(met: bool, run_id: str = "r", **over) -> CandidateObservation:
    base = dict(candidate_id="fobo:s:aaa", run_id=run_id, observed_at=_TS,
               count=20, n_users=5, met_evidence_bar=met)
    base.update(over)
    return CandidateObservation(**base)


class TestReadiness:
    def test_needs_full_sustained_streak(self) -> None:
        recent = [_o(True), _o(True), _o(True)]
        assert ladder.readiness_met(recent, sustained_runs=3, capability_run_count=5) is True

    def test_a_miss_in_the_window_blocks(self) -> None:
        recent = [_o(True), _o(False), _o(True)]
        assert ladder.readiness_met(recent, sustained_runs=3, capability_run_count=5) is False

    def test_not_enough_runs_yet(self) -> None:
        recent = [_o(True), _o(True)]
        assert ladder.readiness_met(recent, sustained_runs=3, capability_run_count=2) is False


class TestNextStatus:
    def _t(self):
        return ladder.resolve_thresholds(_capability(), _settings())

    def test_new_first_observation_stays_new(self) -> None:
        tr = ladder.next_status(_cand2("new"), _o(False), [_o(False)],
                                run_ordinal=1, capability_run_count=1, thresholds=self._t())
        assert tr.status == "new"

    def test_new_second_observation_becomes_accumulating(self) -> None:
        tr = ladder.next_status(_cand2("new"), _o(False), [_o(False), _o(False)],
                                run_ordinal=2, capability_run_count=2, thresholds=self._t())
        assert tr.status == "accumulating"

    def test_accumulating_to_ready_on_streak(self) -> None:
        recent = [_o(True)] * 5
        tr = ladder.next_status(_cand2("accumulating"), _o(True), recent,
                                run_ordinal=6, capability_run_count=6, thresholds=self._t())
        assert tr.status == "ready" and tr.set_ready_at is True

    def test_ready_falls_back_when_evidence_fades(self) -> None:
        recent = [_o(False), _o(True), _o(True), _o(True), _o(True)]
        tr = ladder.next_status(_cand2("ready"), _o(False), recent,
                                run_ordinal=7, capability_run_count=7, thresholds=self._t())
        assert tr.status == "accumulating" and tr.note

    def test_accepted_and_promoted_are_stable(self) -> None:
        for st in ("accepted", "promoted"):
            tr = ladder.next_status(_cand2(st), _o(True), [_o(True)] * 5,
                                    run_ordinal=9, capability_run_count=9, thresholds=self._t())
            assert tr.status == st

    def test_snoozed_unsnoozes_when_ordinal_passes(self) -> None:
        c = _cand2("snoozed", snooze_until_run=5)
        tr = ladder.next_status(c, _o(True), [_o(True)],
                                run_ordinal=5, capability_run_count=5, thresholds=self._t())
        assert tr.status == "accumulating"

    def test_snoozed_stays_when_ordinal_not_reached(self) -> None:
        c = _cand2("snoozed", snooze_until_run=9)
        tr = ladder.next_status(c, _o(True), [_o(True)],
                                run_ordinal=5, capability_run_count=5, thresholds=self._t())
        assert tr.status == "snoozed"

    def test_stale_reactivates_on_observation(self) -> None:
        tr = ladder.next_status(_cand2("stale"), _o(False), [_o(False), _o(False)],
                                run_ordinal=8, capability_run_count=8, thresholds=self._t())
        assert tr.status == "accumulating"

    def test_rejected_reopens_on_material_change(self) -> None:
        c = _cand2("rejected",
                   current_evidence={"count_at_rejection": 20, "n_users_at_rejection": 4})
        tr = ladder.next_status(c, _o(True, count=40, n_users=5), [_o(True)],
                                run_ordinal=8, capability_run_count=8, thresholds=self._t())
        assert tr.status == "accumulating" and tr.decision_action == "reopen"

    def test_rejected_stays_without_material_change(self) -> None:
        c = _cand2("rejected",
                   current_evidence={"count_at_rejection": 20, "n_users_at_rejection": 4})
        tr = ladder.next_status(c, _o(True, count=22, n_users=4), [_o(True)],
                                run_ordinal=8, capability_run_count=8, thresholds=self._t())
        assert tr.status == "rejected"


class TestAdvanceUnobserved:
    def test_stale_after_history_limit_runs(self) -> None:
        tr = ladder.advance_unobserved(_cand2("accumulating"),
                                       run_ordinal=25, last_seen_ordinal=4, history_limit=20)
        assert tr is not None and tr.status == "stale"

    def test_not_yet_stale(self) -> None:
        assert ladder.advance_unobserved(_cand2("accumulating"),
                                         run_ordinal=10, last_seen_ordinal=4,
                                         history_limit=20) is None

    def test_unsnooze_even_when_unobserved(self) -> None:
        tr = ladder.advance_unobserved(_cand2("snoozed", snooze_until_run=8),
                                       run_ordinal=8, last_seen_ordinal=3, history_limit=20)
        assert tr is not None and tr.status == "accumulating"

    def test_terminal_states_untouched(self) -> None:
        for st in ("promoted", "rejected", "accepted"):
            assert ladder.advance_unobserved(_cand2(st), run_ordinal=99,
                                             last_seen_ordinal=1, history_limit=20) is None


class TestRung2Thresholds:
    def test_rung2_defaults_and_overrides(self) -> None:
        t = ladder.resolve_thresholds(_capability(), _settings())
        assert t.rung2_min_answer_spans == 10 and t.rung2_determinism_score == 0.8
        assert t.rung2_sustained_runs == 3
        assert t.cluster_fuzz_threshold == 90
        t2 = ladder.resolve_thresholds(
            _capability({"rung2_determinism_score": 0.6, "rung2_sustained_runs": 2}),
            _settings(),
        )
        assert t2.rung2_determinism_score == 0.6 and t2.rung2_sustained_runs == 2


class TestDetectRung2:
    def _in_scope(self, cluster_id, answers, prompts=None):
        prompts = prompts or ["why is there a break of 100k on BUND"] * len(answers)
        return pd.DataFrame([
            dict(span_id=f"{cluster_id}-{i}", trace_id=f"{cluster_id}-t{i}",
                 span_kind="LLM", input_text=p, output_text=a, start_time=i)
            for i, (a, p) in enumerate(zip(answers, prompts, strict=False))
        ])

    def test_eligible_deterministic_cluster_signal(self) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        frame = self._in_scope("ddd", answers)
        cluster = _cluster("ddd", count=14).model_copy(
            update={"span_ids": tuple(frame["span_id"])}
        )
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung2([cluster], [], frame, thresholds=t)
        assert len(signals) == 1
        assert signals[0].eligible is True
        assert signals[0].met_evidence_bar is True  # score > 0.8

    def test_ineligible_cluster_signal_not_met(self) -> None:
        answers = [f"answer {n}" for n in range(4)]
        frame = self._in_scope("eee", answers)
        cluster = _cluster("eee", count=4).model_copy(
            update={"span_ids": tuple(frame["span_id"])}
        )
        t = ladder.resolve_thresholds(_capability(), _settings())
        signals = ladder.detect_rung2([cluster], [], frame, thresholds=t)
        assert signals[0].eligible is False and signals[0].met_evidence_bar is False


class TestNextStatusRung2:
    def _t(self):
        return ladder.resolve_thresholds(_capability(), _settings())

    def test_ineligible_new_becomes_insufficient_data(self) -> None:
        tr = ladder.next_status(_cand2("new"), _o(False), [_o(False)],
                                run_ordinal=1, capability_run_count=1,
                                thresholds=self._t(), eligible=False)
        assert tr.status == "insufficient_data"

    def test_insufficient_data_resumes_when_eligible(self) -> None:
        tr = ladder.next_status(_cand2("insufficient_data"), _o(True), [_o(True), _o(True)],
                                run_ordinal=3, capability_run_count=3,
                                thresholds=self._t(), eligible=True)
        assert tr.status == "accumulating"

    def test_insufficient_data_stays_when_still_ineligible(self) -> None:
        tr = ladder.next_status(_cand2("insufficient_data"), _o(False), [_o(False)],
                                run_ordinal=3, capability_run_count=3,
                                thresholds=self._t(), eligible=False)
        assert tr.status == "insufficient_data"
