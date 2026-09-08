"""Tests for the capability_jobs table CRUD on Store."""

import sqlite3

import pytest


class TestJobStore:
    def test_enqueue_then_get_round_trips(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {"replace_today": True, "from": None})
        job = tmp_store.get_job("j1")
        assert job["capability_id"] == "fobo"
        assert job["state"] == "queued"
        assert job["params"] == {"replace_today": True, "from": None}
        assert job["run_id"] is None and job["started_at"] is None

    def test_get_unknown_is_none(self, tmp_store) -> None:
        assert tmp_store.get_job("nope") is None

    def test_frame_newest_first_scoped_and_limited(self, tmp_store) -> None:
        for i in range(4):
            tmp_store.enqueue_job(f"a{i}", "fobo", {})
        tmp_store.enqueue_job("b0", "plex", {})
        frame = tmp_store.capability_jobs_frame("fobo", limit=2)
        assert list(frame["job_id"]) == ["a3", "a2"]
        assert set(tmp_store.capability_jobs_frame("plex")["job_id"]) == {"b0"}

    def test_claim_next_takes_oldest_queued_and_marks_running(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {})
        tmp_store.enqueue_job("j2", "fobo", {})
        first = tmp_store.claim_next_job()
        assert first["job_id"] == "j1"
        assert first["state"] == "running" and first["started_at"] is not None
        assert tmp_store.get_job("j1")["state"] == "running"
        assert tmp_store.claim_next_job()["job_id"] == "j2"
        assert tmp_store.claim_next_job() is None

    def test_finish_job_sets_terminal_fields(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {})
        tmp_store.claim_next_job()
        tmp_store.finish_job("j1", run_id="2026-07-21T12:00:00+00:00", state="done")
        job = tmp_store.get_job("j1")
        assert job["state"] == "done"
        assert job["run_id"] == "2026-07-21T12:00:00+00:00"
        assert job["finished_at"] is not None and job["error"] is None

    def test_finish_job_error_records_message(self, tmp_store) -> None:
        tmp_store.enqueue_job("j1", "fobo", {})
        tmp_store.claim_next_job()
        tmp_store.finish_job("j1", run_id=None, state="error", error="RuntimeError: boom")
        job = tmp_store.get_job("j1")
        assert job["state"] == "error" and job["error"] == "RuntimeError: boom"

    def test_reset_orphaned_jobs(self, tmp_store) -> None:
        tmp_store.enqueue_job("q", "fobo", {})          # queued
        tmp_store.enqueue_job("r", "fobo", {})
        tmp_store.claim_next_job()                       # 'q' -> running (oldest)
        tmp_store.enqueue_job("d", "fobo", {})
        tmp_store.claim_next_job()                       # 'r' -> running
        tmp_store.finish_job("r", run_id="x", state="done")
        n = tmp_store.reset_orphaned_jobs()
        assert n == 2                                    # 'q' running + 'd' queued
        assert tmp_store.get_job("q")["state"] == "error"
        assert tmp_store.get_job("d")["state"] == "error"
        assert tmp_store.get_job("r")["state"] == "done"

    def test_schema_rejects_unknown_state(self, tmp_store) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            tmp_store._conn.execute(
                "INSERT INTO capability_jobs (job_id, capability_id, state, enqueued_at) "
                "VALUES ('x', 'fobo', 'wobbly', '2026-01-01')"
            )

    def test_store_is_a_context_manager(self, tmp_path) -> None:
        from phoenix_scraper.storage import Store
        with Store(tmp_path / "cm.db") as s:
            s.enqueue_job("j1", "fobo", {})
        with Store(tmp_path / "cm.db") as s2:
            assert s2.get_job("j1")["state"] == "queued"
