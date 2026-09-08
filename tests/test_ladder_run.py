"""update_rung1: candidates + observations + state machine across runs."""

from datetime import UTC, datetime, timedelta

import pytest

from phoenix_scraper import ladder
from phoenix_scraper.config import Settings
from phoenix_scraper.ladder import Rung1Signal
from phoenix_scraper.ladder_run import update_rung1
from phoenix_scraper.models import Capability, CapabilityFilter

TS = datetime(2026, 9, 7, 12, tzinfo=UTC)


def _cap(thresholds=None) -> Capability:
    return Capability(id="fobo", name="FOBO",
                      filter=CapabilityFilter(workflow_stage="fobo_recon"),
                      thresholds=thresholds or {})


def _sig(cid="aaa", *, count=20, n_users=5, met=True, subtype="new_skill",
         matched_skill=None, score=1.0) -> Rung1Signal:
    return Rung1Signal(
        cluster_id=cid, subtype=subtype, title=f"why {cid}", signature=f"sig {cid}",
        matched_skill=matched_skill, score=score, count=count, n_users=n_users,
        n_sessions=count, total_cost_usd=1.0, route_len_avg=3.0, long_route=False,
        met_evidence_bar=met,
    )


@pytest.fixture()
def t():
    return ladder.resolve_thresholds(_cap(), Settings(db_path="x.db"))


def _run(store, cap, t, signals, *, run_id, ordinal, count, at):
    return update_rung1(
        store, cap, run_id=run_id, run_ordinal=ordinal, capability_run_count=count,
        observed_at=at, signals=signals, thresholds=t, history_limit=20,
    )


class TestUpdateRung1:
    def test_creates_candidate_and_observation(self, tmp_store, t) -> None:
        out = _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 1
        c = tmp_store.get_candidate("fobo:s:aaa")
        assert c is not None and c.status == "new" and c.subtype == "new_skill"
        obs = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert len(obs) == 1 and obs.iloc[0]["count"] == 20

    def test_second_run_moves_to_accumulating(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r1", ordinal=1, count=1, at=TS)
        _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r2", ordinal=2, count=2,
             at=TS + timedelta(days=1))
        assert tmp_store.get_candidate("fobo:s:aaa").status == "accumulating"

    def test_sustained_streak_reaches_ready(self, tmp_store, t) -> None:
        for i in range(1, 7):
            _run(tmp_store, _cap(), t, [_sig("aaa", met=True)],
                 run_id=f"r{i}", ordinal=i, count=i, at=TS + timedelta(days=i))
        c = tmp_store.get_candidate("fobo:s:aaa")
        assert c.status == "ready" and c.ready_at is not None

    def test_crossed_threshold_flag(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t, [_sig("aaa", met=False)], run_id="r1", ordinal=1,
             count=1, at=TS)
        out = _run(tmp_store, _cap(), t, [_sig("aaa", met=True)], run_id="r2", ordinal=2,
                   count=2, at=TS + timedelta(days=1))
        assert "fobo:s:aaa" in out.crossed
        obs = tmp_store.candidate_observations_frame("fobo:s:aaa")
        assert obs.iloc[-1]["crossed_threshold"] == 1

    def test_unobserved_candidate_goes_stale(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t, [_sig("aaa")], run_id="r01", ordinal=1, count=1, at=TS)
        for i in range(2, 23):
            _run(tmp_store, _cap(), t, [_sig("bbb")], run_id=f"r{i:02d}", ordinal=i,
                 count=i, at=TS + timedelta(days=i))
        assert tmp_store.get_candidate("fobo:s:aaa").status == "stale"

    def test_strengthen_subtype_recorded(self, tmp_store, t) -> None:
        _run(tmp_store, _cap(), t,
             [_sig("ccc", subtype="strengthen_skill", matched_skill="fobo-triage", score=0.3)],
             run_id="r1", ordinal=1, count=1, at=TS)
        c = tmp_store.get_candidate("fobo:s:ccc")
        assert c.subtype == "strengthen_skill" and c.matched_skill == "fobo-triage"

    def test_notes_report_ready_and_new(self, tmp_store, t) -> None:
        out = _run(tmp_store, _cap(), t, [_sig("aaa"), _sig("bbb")],
                   run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 2
        assert any("Rung 1" in n for n in out.notes)
