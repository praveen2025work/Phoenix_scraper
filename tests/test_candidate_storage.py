"""Tests for the candidates / observations / decisions tables on Store."""

from datetime import UTC, datetime

from phoenix_scraper.models import Candidate, CandidateDecision, CandidateObservation

TS = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)


def _cand(cid: str = "fobo:s:aaa", cap: str = "fobo", **over) -> Candidate:
    base = dict(
        candidate_id=cid, capability_id=cap, rung="skill", subtype="new_skill",
        cluster_id=cid.split(":")[-1], title="why recon break", signature="why recon break",
        first_seen_run_id="r1", first_seen_at=TS, last_seen_run_id="r1", last_seen_at=TS,
    )
    base.update(over)
    return Candidate(**base)


def _obs(cid: str, run_id: str, **over) -> CandidateObservation:
    base = dict(candidate_id=cid, run_id=run_id, observed_at=TS, count=20, n_users=5)
    base.update(over)
    return CandidateObservation(**base)


class TestCandidateCrud:
    def test_upsert_then_get_round_trips(self, tmp_store) -> None:
        c = _cand(status="ready", matched_skill="fobo-triage",
                  promoted_artifact_paths=("capabilities/fobo/skills/x.md",),
                  current_evidence={"count": 20})
        tmp_store.upsert_candidate(c)
        assert tmp_store.get_candidate("fobo:s:aaa") == c

    def test_get_unknown_is_none(self, tmp_store) -> None:
        assert tmp_store.get_candidate("nope") is None

    def test_upsert_replaces(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        tmp_store.upsert_candidate(_cand(status="accumulating"))
        assert tmp_store.get_candidate("fobo:s:aaa").status == "accumulating"
        assert len(tmp_store.candidates_frame("fobo")) == 1

    def test_candidates_frame_filters(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand("fobo:s:aaa", status="ready"))
        tmp_store.upsert_candidate(_cand("fobo:s:bbb", status="rejected"))
        tmp_store.upsert_candidate(_cand("fobo:d:ccc", rung="deterministic", status="ready"))
        assert len(tmp_store.candidates_frame("fobo")) == 3
        assert len(tmp_store.candidates_frame("fobo", status="ready")) == 2
        assert len(tmp_store.candidates_frame("fobo", rung="skill")) == 2
        assert len(tmp_store.candidates_frame("fobo", rung="skill", status="ready")) == 1


class TestObservations:
    def test_record_then_frame_oldest_first(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "2026-09-05T10:00:00+00:00"))
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "2026-09-07T10:00:00+00:00"))
        frame = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert list(frame["run_id"]) == [
            "2026-09-05T10:00:00+00:00", "2026-09-07T10:00:00+00:00",
        ]

    def test_re_record_same_run_replaces(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "r1", count=10))
        tmp_store.record_candidate_observation(_obs("fobo:s:aaa", "r1", count=99))
        frame = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert len(frame) == 1 and frame.iloc[0]["count"] == 99

    def test_recent_observations_newest_first(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        for day in (1, 2, 3, 4):
            tmp_store.record_candidate_observation(
                _obs("fobo:s:aaa", f"2026-09-0{day}T10:00:00+00:00", count=day)
            )
        recent = tmp_store.recent_candidate_observations("fobo:s:aaa", 2)
        assert [o.count for o in recent] == [4, 3]
        assert all(isinstance(o, CandidateObservation) for o in recent)

    def test_prune_keeps_newest(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        for day in range(1, 6):
            tmp_store.record_candidate_observation(
                _obs("fobo:s:aaa", f"2026-09-0{day}T10:00:00+00:00")
            )
        tmp_store.prune_candidate_observations("fobo:s:aaa", 2)
        frame = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert list(frame["run_id"]) == [
            "2026-09-04T10:00:00+00:00", "2026-09-05T10:00:00+00:00",
        ]


class TestDecisions:
    def test_record_returns_id_and_frame_ordered(self, tmp_store) -> None:
        tmp_store.upsert_candidate(_cand())
        i1 = tmp_store.record_candidate_decision(CandidateDecision(
            candidate_id="fobo:s:aaa", action="snooze", actor="a", note="q3 freeze",
            created_at=TS,
        ))
        i2 = tmp_store.record_candidate_decision(CandidateDecision(
            candidate_id="fobo:s:aaa", action="accept", actor="b", created_at=TS,
        ))
        assert i2 > i1
        frame = tmp_store.candidate_decisions_frame("fobo:s:aaa")
        assert list(frame["action"]) == ["snooze", "accept"]
        assert list(frame["actor"]) == ["a", "b"]


class TestRunOrdinal:
    def test_ordinal_counts_runs_up_to_and_including(
        self, seeded_store, tmp_path, settings
    ) -> None:
        from phoenix_scraper import capability as cap_mod
        from phoenix_scraper.capability_run import run_capability_analysis
        from phoenix_scraper.models import CapabilityFilter
        root = tmp_path / "caps"
        cap = cap_mod.scaffold_capability(
            root, "fobo", cap_filter=CapabilityFilter(workflow_stage="fobo_recon")
        )
        s = settings.model_copy(update={"capabilities_dir": root})
        r1 = run_capability_analysis(seeded_store, s, cap,
                                     now=datetime(2026, 7, 20, 12, tzinfo=UTC))
        r2 = run_capability_analysis(seeded_store, s, cap,
                                     now=datetime(2026, 7, 21, 12, tzinfo=UTC))
        assert seeded_store.capability_run_ordinal("fobo") == 2
        assert seeded_store.capability_run_ordinal("fobo", r1.run.run_id) == 1
        assert seeded_store.capability_run_ordinal("fobo", r2.run.run_id) == 2
        assert seeded_store.capability_run_ordinal("other") == 0
