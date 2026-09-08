"""update_rung1 / update_rung2: candidates + observations + state machine across runs."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from phoenix_scraper import ladder
from phoenix_scraper.config import Settings
from phoenix_scraper.ladder import Rung1Signal, detect_rung2
from phoenix_scraper.ladder_run import update_rung1, update_rung2
from phoenix_scraper.models import Capability, CapabilityFilter, PromptCluster

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


def _r2_frame(cluster_id, answers):
    return pd.DataFrame([
        dict(span_id=f"{cluster_id}-{i}", trace_id=f"{cluster_id}-t{i}",
             span_kind="LLM", input_text="why is there a break of 100k on BUND",
             output_text=a, start_time=i)
        for i, a in enumerate(answers)
    ])


def _r2_signals(cluster_id, answers, t):
    frame = _r2_frame(cluster_id, answers)
    cluster = PromptCluster(
        cluster_id=cluster_id, signature=f"sig {cluster_id}",
        representative="why is there a break", count=len(answers),
        span_ids=tuple(frame["span_id"]),
    )
    return detect_rung2([cluster], [], frame, thresholds=t)


def _run2(store, cap, t, signals, *, run_id, ordinal, count, at):
    return update_rung2(
        store, cap, run_id=run_id, run_ordinal=ordinal, capability_run_count=count,
        observed_at=at, signals=signals, thresholds=t, history_limit=20,
    )


class TestUpdateRung2:
    def test_deterministic_cluster_creates_candidate(self, tmp_store, t) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        out = _run2(tmp_store, _cap(), t, _r2_signals("ddd", answers, t),
                    run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 1
        c = tmp_store.get_candidate("fobo:d:ddd")
        assert c is not None and c.rung == "deterministic"

    def test_variable_cluster_below_floor_is_not_recorded(self, tmp_store, t) -> None:
        stems = ["a timing mismatch on settlement drove the gap",
                 "cash projections shifted after the treasury update",
                 "the desk flagged unusual credit spread widening",
                 "position limits were breached intraday then corrected"]
        answers = [stems[i % len(stems)] + f" note {i}" for i in range(14)]
        out = _run2(tmp_store, _cap(), t, _r2_signals("var", answers, t),
                    run_id="r1", ordinal=1, count=1, at=TS)
        assert out.n_candidates == 0
        assert tmp_store.get_candidate("fobo:d:var") is None

    def test_ineligible_existing_candidate_goes_insufficient_data(self, tmp_store, t) -> None:
        good = [f"The break of {n}k on BUND is unsettled." for n in range(14)]
        _run2(tmp_store, _cap(), t, _r2_signals("ddd", good, t),
              run_id="r1", ordinal=1, count=1, at=TS)
        thin = [f"The break of {n}k on BUND is unsettled." for n in range(4)]
        out = _run2(tmp_store, _cap(), t, _r2_signals("ddd", thin, t),
                    run_id="r2", ordinal=2, count=2, at=TS + timedelta(days=1))
        assert tmp_store.get_candidate("fobo:d:ddd").status == "insufficient_data"
        assert out.n_insufficient == 1

    def test_sustained_reaches_ready(self, tmp_store, t) -> None:
        answers = [f"The break of {n}k on BUND is an unsettled trade." for n in range(14)]
        for i in range(1, 4):
            _run2(tmp_store, _cap(), t, _r2_signals("ddd", answers, t),
                  run_id=f"r{i}", ordinal=i, count=i, at=TS + timedelta(days=i))
        assert tmp_store.get_candidate("fobo:d:ddd").status == "ready"
