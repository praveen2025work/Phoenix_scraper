"""Tests for Capability settings, models, and the capabilities/<id>/ disk layer."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from phoenix_scraper import capability as cap_mod
from phoenix_scraper.config import Settings
from phoenix_scraper.models import Capability, CapabilityFilter, QueryFilters

# Match the repo convention: never let a developer's real .env leak into a test.
_S = dict(_env_file=None)


class TestSettings:
    def test_capabilities_dir_defaults_to_capabilities(self) -> None:
        assert Settings(**_S).capabilities_dir == Path("capabilities")

    def test_capabilities_dir_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("PHEONIX_CAPABILITIES_DIR", "/tmp/caps")
        # _env_file=None disables the dotenv file, NOT os.environ — the var is read.
        assert Settings(**_S).capabilities_dir == Path("/tmp/caps")

    def test_operator_name_defaults_blank(self) -> None:
        assert Settings(**_S).operator_name == ""


class TestCapabilityModels:
    def test_defaults(self) -> None:
        cap = Capability(id="fobo", name="FOBO reconciliation")
        assert cap.description == ""
        assert cap.window_days == 30
        assert cap.status == "active"
        assert cap.thresholds == {}
        assert cap.filter == CapabilityFilter()

    def test_filter_is_frozen(self) -> None:
        f = CapabilityFilter(project="pnl-agent")
        with pytest.raises(ValidationError):
            f.project = "other"  # type: ignore[misc]

    def test_thresholds_default_is_not_shared(self) -> None:
        a = Capability(id="a", name="a")
        b = Capability(id="b", name="b")
        assert a.thresholds is not b.thresholds


class TestValidateId:
    @pytest.mark.parametrize("good", ["fobo", "flash-vs-formal", "plex2", "a1"])
    def test_accepts_kebab(self, good: str) -> None:
        assert cap_mod.validate_id(good) == good

    @pytest.mark.parametrize(
        "bad", ["", "1fobo", "FOBO", "fo bo", "fobo_recon", "-fobo", "a" * 65]
    )
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(ValueError):
            cap_mod.validate_id(bad)


class TestLoadDump:
    def _write(self, root: Path, cap_id: str, text: str) -> Path:
        d = root / cap_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / "capability.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_load_full(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "fobo",
            "id: fobo\nname: FOBO reconciliation\n"
            "description: Break triage.\n"
            "filter:\n  project: pnl-agent\n  workflow_stage: fobo_recon\n"
            "  asset_class: null\n"
            "window_days: 45\n"
            "thresholds:\n  rung1_min_users: 4\n"
            "status: paused\n",
        )
        cap = cap_mod.load_capability(tmp_path, "fobo")
        assert cap.id == "fobo"
        assert cap.name == "FOBO reconciliation"
        assert cap.filter.project == "pnl-agent"
        assert cap.filter.workflow_stage == "fobo_recon"
        assert cap.filter.asset_class is None
        assert cap.window_days == 45
        assert cap.thresholds == {"rung1_min_users": 4}
        assert cap.status == "paused"

    def test_load_minimal_fills_defaults(self, tmp_path: Path) -> None:
        self._write(tmp_path, "plex", "id: plex\nname: PLEX\n")
        cap = cap_mod.load_capability(tmp_path, "plex")
        assert cap.filter == CapabilityFilter()
        assert cap.window_days == 30
        assert cap.status == "active"

    def test_load_blank_filter_values_become_none(self, tmp_path: Path) -> None:
        self._write(
            tmp_path, "plex",
            "id: plex\nname: PLEX\nfilter:\n  project: '  '\n  search: ''\n",
        )
        cap = cap_mod.load_capability(tmp_path, "plex")
        assert cap.filter.project is None
        assert cap.filter.search is None

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            cap_mod.load_capability(tmp_path, "ghost")

    def test_load_non_mapping_raises(self, tmp_path: Path) -> None:
        self._write(tmp_path, "bad", "- just\n- a\n- list\n")
        with pytest.raises(ValueError):
            cap_mod.load_capability(tmp_path, "bad")

    def test_load_bad_status_falls_back_to_active(self, tmp_path: Path) -> None:
        self._write(tmp_path, "x", "id: x\nname: X\nstatus: wobbly\n")
        assert cap_mod.load_capability(tmp_path, "x").status == "active"

    def test_dump_round_trips(self, tmp_path: Path) -> None:
        original = Capability(
            id="fobo",
            name="FOBO",
            description="d",
            filter=CapabilityFilter(project="pnl-agent", asset_class="fx"),
            window_days=14,
            thresholds={"rung2_determinism_score": 0.9},
            status="paused",
        )
        (tmp_path / "fobo").mkdir()
        (tmp_path / "fobo" / "capability.yaml").write_text(
            cap_mod.dump_capability(original), encoding="utf-8"
        )
        assert cap_mod.load_capability(tmp_path, "fobo") == original

    def test_load_rejects_traversal_id(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            cap_mod.load_capability(tmp_path, "../x")

    def test_load_null_numeric_values_fall_back(self, tmp_path: Path) -> None:
        d = tmp_path / "x"
        d.mkdir()
        (d / "capability.yaml").write_text(
            "id: x\nname: X\nwindow_days:\nthresholds:\n  rung1_min_users:\n",
            encoding="utf-8",
        )
        cap = cap_mod.load_capability(tmp_path, "x")
        assert cap.window_days == 30
        assert cap.thresholds == {}


class TestScaffold:
    def test_creates_tree_and_yaml(self, tmp_path: Path) -> None:
        cap = cap_mod.scaffold_capability(
            tmp_path, "fobo", name="FOBO", description="triage",
            cap_filter=CapabilityFilter(project="pnl-agent", workflow_stage="fobo_recon"),
            window_days=21,
        )
        assert cap.id == "fobo" and cap.window_days == 21
        assert (tmp_path / "fobo" / "capability.yaml").is_file()
        assert (tmp_path / "fobo" / "skills").is_dir()
        assert (tmp_path / "fobo" / "deterministic").is_dir()
        # round-trips through disk
        assert cap_mod.load_capability(tmp_path, "fobo") == cap

    def test_rejects_duplicate(self, tmp_path: Path) -> None:
        cap_mod.scaffold_capability(tmp_path, "fobo", name="FOBO")
        with pytest.raises(FileExistsError):
            cap_mod.scaffold_capability(tmp_path, "fobo", name="again")

    def test_rejects_bad_id(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            cap_mod.scaffold_capability(tmp_path, "Bad_Id", name="x")


class TestListing:
    def test_lists_only_dirs_with_yaml(self, tmp_path: Path) -> None:
        cap_mod.scaffold_capability(tmp_path, "fobo", name="FOBO")
        cap_mod.scaffold_capability(tmp_path, "plex", name="PLEX")
        (tmp_path / "not-a-cap").mkdir()
        assert cap_mod.list_capability_ids(tmp_path) == ["fobo", "plex"]

    def test_list_missing_root_is_empty(self, tmp_path: Path) -> None:
        assert cap_mod.list_capability_ids(tmp_path / "nope") == []

    def test_load_all_skips_malformed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cap_mod.scaffold_capability(tmp_path, "good", name="Good")
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "capability.yaml").write_text("- nope\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            caps = cap_mod.load_all_capabilities(tmp_path)
        assert [c.id for c in caps] == ["good"]
        assert "Skipping capability" in caplog.text

    def test_load_all_skips_syntactically_corrupt_yaml(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cap_mod.scaffold_capability(tmp_path, "good", name="Good")
        (tmp_path / "broken").mkdir()
        (tmp_path / "broken" / "capability.yaml").write_text(
            "id: broken\nname: [unclosed\n\tbad: tab\n", encoding="utf-8"
        )
        with caplog.at_level(logging.WARNING):
            caps = cap_mod.load_all_capabilities(tmp_path)
        assert [c.id for c in caps] == ["good"]
        assert "Skipping capability" in caplog.text


class TestSkillDirs:
    def test_returns_skills_dir_when_present(self, tmp_path: Path) -> None:
        cap_mod.scaffold_capability(tmp_path, "fobo", name="FOBO")
        assert cap_mod.capability_skill_dirs(tmp_path, "fobo") == [
            tmp_path / "fobo" / "skills"
        ]

    def test_empty_when_absent(self, tmp_path: Path) -> None:
        assert cap_mod.capability_skill_dirs(tmp_path, "ghost") == []


class TestQueryFilters:
    def test_maps_every_filter_dimension(self) -> None:
        cap = Capability(
            id="fobo", name="FOBO",
            filter=CapabilityFilter(
                project="pnl-agent", workflow_stage="fobo_recon",
                asset_class="fx", model_name="claude", search="break",
            ),
        )
        start = datetime(2026, 8, 1, tzinfo=UTC)
        end = datetime(2026, 9, 1, tzinfo=UTC)
        qf = cap_mod.capability_query_filters(cap, start=start, end=end, limit=500)
        assert isinstance(qf, QueryFilters)
        assert qf.project == "pnl-agent"
        assert qf.workflow_stage == "fobo_recon"
        assert qf.asset_class == "fx"
        assert qf.model_name == "claude"
        assert qf.search == "break"
        assert qf.start == start and qf.end == end and qf.limit == 500

    def test_defaults(self) -> None:
        qf = cap_mod.capability_query_filters(Capability(id="a", name="a"))
        assert qf.start is None and qf.end is None and qf.limit == 100_000
        assert qf.project is None
