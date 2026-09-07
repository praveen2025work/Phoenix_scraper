"""Tests for Capability settings, models, and the capabilities/<id>/ disk layer."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from phoenix_scraper.config import Settings
from phoenix_scraper.models import Capability, CapabilityFilter

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
        from phoenix_scraper import capability as cap_mod

        assert cap_mod.validate_id(good) == good

    @pytest.mark.parametrize(
        "bad", ["", "1fobo", "FOBO", "fo bo", "fobo_recon", "-fobo", "a" * 65]
    )
    def test_rejects(self, bad: str) -> None:
        from phoenix_scraper import capability as cap_mod

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
        from phoenix_scraper import capability as cap_mod

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
        from phoenix_scraper import capability as cap_mod

        self._write(tmp_path, "plex", "id: plex\nname: PLEX\n")
        cap = cap_mod.load_capability(tmp_path, "plex")
        assert cap.filter == CapabilityFilter()
        assert cap.window_days == 30
        assert cap.status == "active"

    def test_load_blank_filter_values_become_none(self, tmp_path: Path) -> None:
        from phoenix_scraper import capability as cap_mod

        self._write(
            tmp_path, "plex",
            "id: plex\nname: PLEX\nfilter:\n  project: '  '\n  search: ''\n",
        )
        cap = cap_mod.load_capability(tmp_path, "plex")
        assert cap.filter.project is None
        assert cap.filter.search is None

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        from phoenix_scraper import capability as cap_mod

        with pytest.raises(FileNotFoundError):
            cap_mod.load_capability(tmp_path, "ghost")

    def test_load_non_mapping_raises(self, tmp_path: Path) -> None:
        from phoenix_scraper import capability as cap_mod

        self._write(tmp_path, "bad", "- just\n- a\n- list\n")
        with pytest.raises(ValueError):
            cap_mod.load_capability(tmp_path, "bad")

    def test_load_bad_status_falls_back_to_active(self, tmp_path: Path) -> None:
        from phoenix_scraper import capability as cap_mod

        self._write(tmp_path, "x", "id: x\nname: X\nstatus: wobbly\n")
        assert cap_mod.load_capability(tmp_path, "x").status == "active"

    def test_dump_round_trips(self, tmp_path: Path) -> None:
        from phoenix_scraper import capability as cap_mod

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
