"""Tests for the capability_runs / snapshots / members tables on Store."""

import json
from datetime import UTC, datetime

from phoenix_scraper.models import CapabilityRun

RUN_TS = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)


def _run(run_id: str = "2026-09-07T10:00:00+00:00", cap: str = "fobo", **over) -> CapabilityRun:
    base = dict(
        run_id=run_id,
        capability_id=cap,
        started_at=RUN_TS,
        finished_at=RUN_TS,
        window_start=datetime(2026, 8, 8, tzinfo=UTC),
        window_end=datetime(2026, 9, 7, tzinfo=UTC),
        n_spans=500,
        n_in_scope_spans=210,
        n_clusters=3,
        status="ok",
        notes=(),
    )
    base.update(over)
    return CapabilityRun(**base)


def _snap(run_id: str, cluster_id: str, cap: str = "fobo", **over) -> dict:
    base = dict(
        capability_id=cap, run_id=run_id, cluster_id=cluster_id,
        signature="why recon break of <num> on <book>",
        representative="Why is there a recon break of 100k on CDS_IG_NY?",
        count=10, n_users=4, skill_name="fobo-break-triage",
        covered=1, in_scope=1, route_len_avg=3.0, long_route=0,
        first_seen=None, last_seen=None,
    )
    base.update(over)
    return base


class TestRecordAndRead:
    def test_record_then_runs_frame(self, tmp_store) -> None:
        run = _run()
        tmp_store.record_capability_run(
            run, [_snap(run.run_id, "aaa"), _snap(run.run_id, "bbb", count=5)],
            [("aaa", "s1"), ("aaa", "s2"), ("bbb", "s3")], history_limit=20,
        )
        frame = tmp_store.capability_runs_frame("fobo")
        assert len(frame) == 1
        row = frame.iloc[0]
        assert row["run_id"] == run.run_id
        assert row["n_in_scope_spans"] == 210
        assert row["status"] == "ok"
        assert row["skill_hashes_json"] == "{}"

    def test_skill_hashes_round_trip(self, tmp_store) -> None:
        run = _run(skill_hashes={"a.md": "abc123"})
        tmp_store.record_capability_run(run, [], [], history_limit=20)
        row = tmp_store.capability_runs_frame("fobo").iloc[0]
        assert json.loads(row["skill_hashes_json"]) == {"a.md": "abc123"}

    def test_snapshot_and_members_round_trip(self, tmp_store) -> None:
        run = _run()
        tmp_store.record_capability_run(
            run, [_snap(run.run_id, "aaa")], [("aaa", "s1"), ("aaa", "s2")],
            history_limit=20,
        )
        snaps = tmp_store.capability_run_snapshot_frame("fobo", run.run_id)
        assert list(snaps["cluster_id"]) == ["aaa"]
        assert snaps.iloc[0]["skill_name"] == "fobo-break-triage"
        members = tmp_store.capability_cluster_members_frame("fobo", run.run_id)
        assert set(members["span_id"]) == {"s1", "s2"}

    def test_snapshot_frame_none_run_is_empty_with_columns(self, tmp_store) -> None:
        frame = tmp_store.capability_run_snapshot_frame("fobo", None)
        assert frame.empty
        assert "cluster_id" in frame.columns and "count" in frame.columns

    def test_re_record_same_run_replaces_snapshots(self, tmp_store) -> None:
        run = _run()
        tmp_store.record_capability_run(
            run, [_snap(run.run_id, "aaa")], [("aaa", "s1")], history_limit=20
        )
        tmp_store.record_capability_run(
            run, [_snap(run.run_id, "zzz")], [("zzz", "s9")], history_limit=20
        )
        snaps = tmp_store.capability_run_snapshot_frame("fobo", run.run_id)
        assert list(snaps["cluster_id"]) == ["zzz"]
        assert len(tmp_store.capability_runs_frame("fobo")) == 1

    def test_previous_capability_run_id(self, tmp_store) -> None:
        r1 = _run("2026-09-05T10:00:00+00:00")
        r2 = _run("2026-09-06T10:00:00+00:00")
        r3 = _run("2026-09-07T10:00:00+00:00")
        for r in (r1, r2, r3):
            tmp_store.record_capability_run(
                r, [_snap(r.run_id, "aaa")], [("aaa", "s1")], history_limit=20
            )
        assert tmp_store.previous_capability_run_id("fobo") == r3.run_id
        assert tmp_store.previous_capability_run_id("fobo", before=r3.run_id) == r2.run_id
        assert tmp_store.previous_capability_run_id("fobo", before=r1.run_id) is None
        assert tmp_store.previous_capability_run_id("other") is None

    def test_prune_keeps_newest_n_per_capability(self, tmp_store) -> None:
        for day in range(1, 6):
            r = _run(f"2026-09-0{day}T10:00:00+00:00")
            tmp_store.record_capability_run(
                r, [_snap(r.run_id, "aaa")], [("aaa", "s1")], history_limit=3
            )
        runs = tmp_store.capability_runs_frame("fobo")
        assert len(runs) == 3
        assert list(runs["run_id"]) == [
            "2026-09-05T10:00:00+00:00", "2026-09-04T10:00:00+00:00", "2026-09-03T10:00:00+00:00",
        ]
        # snapshots + members for pruned runs are gone
        assert tmp_store.capability_run_snapshot_frame("fobo", "2026-09-01T10:00:00+00:00").empty
        assert tmp_store.capability_cluster_members_frame("fobo", "2026-09-01T10:00:00+00:00").empty

    def test_prune_is_per_capability(self, tmp_store) -> None:
        for day in range(1, 4):
            for cap in ("fobo", "plex"):
                r = _run(f"2026-09-0{day}T10:00:00+00:00", cap=cap)
                tmp_store.record_capability_run(
                    r, [_snap(r.run_id, "aaa", cap=cap)], [("aaa", "s1")], history_limit=2,
                )
        assert len(tmp_store.capability_runs_frame("fobo")) == 2
        assert len(tmp_store.capability_runs_frame("plex")) == 2

    def test_latest_run_id_on_day(self, tmp_store) -> None:
        a = _run("2026-09-07T08:00:00+00:00")
        b = _run("2026-09-07T15:00:00+00:00")
        c = _run("2026-09-06T09:00:00+00:00")
        for r in (a, b, c):
            tmp_store.record_capability_run(
                r, [_snap(r.run_id, "aaa")], [("aaa", "s1")], history_limit=20
            )
        assert tmp_store.latest_capability_run_id_on_day("fobo", "2026-09-07") == b.run_id
        assert tmp_store.latest_capability_run_id_on_day("fobo", "2026-09-01") is None

    def test_span_count(self, tmp_store, sample_spans) -> None:
        assert tmp_store.span_count() == 0
        tmp_store.upsert_spans(sample_spans)
        assert tmp_store.span_count() == len(sample_spans)
