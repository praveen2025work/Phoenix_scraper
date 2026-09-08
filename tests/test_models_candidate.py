"""Frozen-model round-trips for the ladder candidate models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from phoenix_scraper.models import Candidate, CandidateDecision, CandidateObservation

TS = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)


def _candidate(**over) -> Candidate:
    base = dict(
        candidate_id="fobo:s:abc123",
        capability_id="fobo",
        rung="skill",
        subtype="new_skill",
        cluster_id="abc123",
        title="Why is there a recon break of <num> on <book>?",
        signature="why recon break of <num> on <book>",
        first_seen_run_id="2026-09-01T10:00:00+00:00",
        first_seen_at=TS,
        last_seen_run_id="2026-09-07T10:00:00+00:00",
        last_seen_at=TS,
    )
    base.update(over)
    return Candidate(**base)


def test_candidate_defaults() -> None:
    c = _candidate()
    assert c.status == "new"
    assert c.matched_skill is None
    assert c.promoted_artifact_paths == ()
    assert c.snooze_until_run is None
    assert c.current_evidence == {}


def test_candidate_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _candidate().status = "ready"


def test_candidate_rejects_bad_status() -> None:
    with pytest.raises(ValidationError):
        _candidate(status="cooking")


def test_observation_defaults() -> None:
    obs = CandidateObservation(
        candidate_id="fobo:s:abc123", run_id="2026-09-07T10:00:00+00:00", observed_at=TS
    )
    assert obs.count == 0 and obs.n_users == 0
    assert obs.score is None
    assert obs.signals == {}
    assert obs.met_evidence_bar is False and obs.crossed_threshold is False


def test_decision_round_trip() -> None:
    d = CandidateDecision(
        candidate_id="fobo:s:abc123", action="accept", actor="alice", created_at=TS
    )
    assert d.note == "" and d.run_id is None and d.id is None
    with pytest.raises(ValidationError):
        CandidateDecision(
            candidate_id="x", action="explode", actor="a", created_at=TS
        )
