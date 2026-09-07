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
