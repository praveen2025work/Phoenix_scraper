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
