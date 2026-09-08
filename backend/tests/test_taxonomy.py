"""Tests for taxonomy keyword maps and level inference."""

import pytest

from phoenix_scraper.taxonomy import (
    ASSET_CLASS_KEYWORDS,
    CAPABILITY_KEYWORDS,
    infer_asset_class,
    infer_capability,
    suggest_level,
)

EXPECTED_ASSET_CLASSES = {"fx", "rates", "equities", "credit", "commodities"}
EXPECTED_CAPABILITIES = {
    "fobo_recon",
    "plex",
    "flash_vs_formal",
    "adjustments",
    "commentary_signoff",
    "break_investigation",
    "data_retrieval",
}


class TestKeywordMaps:
    def test_asset_class_keys_cover_domain(self) -> None:
        assert set(ASSET_CLASS_KEYWORDS) == EXPECTED_ASSET_CLASSES

    def test_capability_keys_cover_domain(self) -> None:
        assert set(CAPABILITY_KEYWORDS) == EXPECTED_CAPABILITIES

    def test_keyword_values_are_nonempty_tuples(self) -> None:
        for mapping in (ASSET_CLASS_KEYWORDS, CAPABILITY_KEYWORDS):
            for key, kws in mapping.items():
                assert isinstance(kws, tuple), key
                assert len(kws) > 0, key
                assert all(isinstance(k, str) and k for k in kws), key


class TestInferAssetClass:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Why is there an FX recon break of 100k on EURUSD?", "fx"),
            ("Run PLEX attribution for the rates desk swap curve", "rates"),
            ("Show me the equities dividend break for the index book", "equities"),
            ("Explain the credit desk CDS spread move", "credit"),
            ("What drove the commodities desk oil P&L today?", "commodities"),
        ],
    )
    def test_known_asset_classes(self, text: str, expected: str) -> None:
        assert infer_asset_class(text) == expected

    def test_unrelated_text_returns_none(self) -> None:
        assert infer_asset_class("convert my report to french") is None

    def test_empty_text_returns_none(self) -> None:
        assert infer_asset_class("") is None

    def test_case_insensitive(self) -> None:
        assert infer_asset_class("fx BREAK on eurusd") == "fx"

    def test_no_substring_false_positive(self) -> None:
        # "fx" must not match inside an unrelated word.
        assert infer_asset_class("please fix the suffix in my document") is None


class TestInferCapability:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Classify today's FOBO reconciliation breaks", "fobo_recon"),
            ("Run PLEX attribution by risk factor", "plex"),
            ("Why does flash differ from formal today?", "flash_vs_formal"),
            ("Post an adjustment for the missing dividend", "adjustments"),
            ("Draft sign-off commentary for the desk", "commentary_signoff"),
            ("Investigate the root cause of this break", "break_investigation"),
            ("Fetch the latest positions and list them", "data_retrieval"),
        ],
    )
    def test_known_capabilities(self, text: str, expected: str) -> None:
        assert infer_capability(text) == expected

    def test_unrelated_text_returns_none(self) -> None:
        assert infer_capability("bonjour, translate this to french") is None

    def test_empty_text_returns_none(self) -> None:
        assert infer_capability("") is None


class TestSuggestLevel:
    def test_asset_class_match_wins(self) -> None:
        level, ac, cap = suggest_level("Why is there an FX recon break on EURUSD?")
        assert level == "asset_class"
        assert ac == "fx"
        assert cap is not None

    def test_capability_only(self) -> None:
        level, ac, cap = suggest_level("Post an adjustment for the missing amount")
        assert level == "capability"
        assert ac is None
        assert cap == "adjustments"

    def test_global_fallback(self) -> None:
        assert suggest_level("convert my report to french") == ("global", None, None)

    def test_does_not_mutate_input(self) -> None:
        text = "Draft sign-off commentary for the rates desk"
        suggest_level(text)
        assert text == "Draft sign-off commentary for the rates desk"
