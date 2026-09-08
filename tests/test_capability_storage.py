"""Tests for the capabilities table CRUD on Store."""

from phoenix_scraper.models import Capability, CapabilityFilter


def _cap(cap_id: str = "fobo", **over) -> Capability:
    base = dict(
        id=cap_id,
        name="FOBO reconciliation",
        description="Break triage.",
        filter=CapabilityFilter(project="pnl-agent", workflow_stage="fobo_recon"),
        window_days=30,
        thresholds={"rung1_min_users": 4.0},
        status="active",
    )
    base.update(over)
    return Capability(**base)


class TestCapabilityCrud:
    def test_frame_empty(self, tmp_store) -> None:
        assert len(tmp_store.capabilities_frame()) == 0

    def test_upsert_then_get_round_trips(self, tmp_store) -> None:
        cap = _cap()
        tmp_store.upsert_capability(cap)
        assert tmp_store.get_capability("fobo") == cap

    def test_get_unknown_is_none(self, tmp_store) -> None:
        assert tmp_store.get_capability("nope") is None

    def test_upsert_updates_in_place(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap())
        tmp_store.upsert_capability(_cap(name="Renamed", status="paused"))
        got = tmp_store.get_capability("fobo")
        assert got.name == "Renamed"
        assert got.status == "paused"
        assert len(tmp_store.capabilities_frame()) == 1

    def test_created_at_is_stable_across_updates(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap())
        first = tmp_store.capabilities_frame().iloc[0]["created_at"]
        tmp_store.upsert_capability(_cap(name="Renamed"))
        row = tmp_store.capabilities_frame().iloc[0]
        assert row["created_at"] == first
        assert row["updated_at"] >= first

    def test_frame_sorted_by_id(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap("plex", name="PLEX"))
        tmp_store.upsert_capability(_cap("fobo"))
        assert list(tmp_store.capabilities_frame()["capability_id"]) == ["fobo", "plex"]

    def test_delete(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap())
        assert tmp_store.delete_capability("fobo") is True
        assert tmp_store.delete_capability("fobo") is False
        assert tmp_store.get_capability("fobo") is None

    def test_null_filter_fields_survive(self, tmp_store) -> None:
        tmp_store.upsert_capability(_cap(filter=CapabilityFilter()))
        assert tmp_store.get_capability("fobo").filter == CapabilityFilter()


class TestCapabilitySchemaGuards:
    def test_schema_rejects_nonpositive_window_days(self, tmp_store) -> None:
        import sqlite3

        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            tmp_store._conn.execute(
                "INSERT INTO capabilities "
                "(capability_id, created_at, updated_at, window_days) "
                "VALUES ('bad', '2026-01-01', '2026-01-01', 0)"
            )

    def test_schema_rejects_unknown_status(self, tmp_store) -> None:
        import sqlite3

        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            tmp_store._conn.execute(
                "INSERT INTO capabilities "
                "(capability_id, created_at, updated_at, status) "
                "VALUES ('bad', '2026-01-01', '2026-01-01', 'wobbly')"
            )

    def test_capability_from_row_coerces_bad_values(self) -> None:
        from phoenix_scraper.storage import _capability_from_row
        row = {
            "capability_id": "x", "name": "X", "description": "",
            "filter_project": None, "filter_workflow_stage": None,
            "filter_asset_class": None, "filter_model_name": None,
            "filter_search": None, "window_days": 0,
            "thresholds_json": "{}", "status": "wobbly",
        }
        cap = _capability_from_row(row)
        assert cap.window_days == 30
        assert cap.status == "active"

    def test_capability_from_row_keeps_good_values(self) -> None:
        from phoenix_scraper.storage import _capability_from_row
        row = {
            "capability_id": "x", "name": "X", "description": "",
            "filter_project": None, "filter_workflow_stage": None,
            "filter_asset_class": None, "filter_model_name": None,
            "filter_search": None, "window_days": 14,
            "thresholds_json": "{}", "status": "paused",
        }
        cap = _capability_from_row(row)
        assert cap.window_days == 14
        assert cap.status == "paused"
