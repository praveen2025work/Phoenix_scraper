"""Tests for prompt normalization and signature generation."""

from phoenix_scraper.normalize import normalize_prompt, prompt_signature


class TestNormalizePrompt:
    def test_casefold_and_whitespace_collapse(self) -> None:
        assert normalize_prompt("  Hello   WORLD  ") == "hello world"

    def test_masks_amount_with_k_suffix(self) -> None:
        assert normalize_prompt("a break of 100k today") == "a break of <num> today"

    def test_masks_amount_variants(self) -> None:
        assert normalize_prompt("moved by 1,250,000") == "moved by <num>"
        assert normalize_prompt("a swing of 3.5m") == "a swing of <num>"
        assert normalize_prompt("about $2bn notional") == "about <num> notional"

    def test_masks_iso_date(self) -> None:
        assert normalize_prompt("pnl move on 2026-07-29") == "pnl move on <date>"

    def test_masks_slash_date(self) -> None:
        assert normalize_prompt("pnl move on 29/07/2026") == "pnl move on <date>"

    def test_masks_month_name_date(self) -> None:
        assert normalize_prompt("pnl move on July 29") == "pnl move on <date>"
        assert normalize_prompt("pnl move on July 29, 2026") == "pnl move on <date>"
        assert normalize_prompt("pnl move on 29 July") == "pnl move on <date>"

    def test_masks_ids(self) -> None:
        assert normalize_prompt("adjustment ADJ-1234 status") == "adjustment <id> status"
        assert normalize_prompt("trade ref TRD_998877 booked") == "trade ref <id> booked"

    def test_masks_concatenated_currency_pair(self) -> None:
        assert normalize_prompt("break on EURUSD") == "break on <ccy>"

    def test_masks_slashed_currency_pair(self) -> None:
        assert normalize_prompt("break on EUR/USD") == "break on <ccy>"

    def test_masks_single_iso_currency_code(self) -> None:
        assert normalize_prompt("convert 100 USD to EUR") == "convert <num> <ccy> to <ccy>"

    def test_plain_words_are_not_masked(self) -> None:
        assert (
            normalize_prompt("Summarise the unexplained breaks by trading book")
            == "summarise the unexplained breaks by trading book"
        )

    def test_desk_mentions_are_masked(self) -> None:
        assert (
            normalize_prompt("Draft sign-off commentary for the rates desk")
            == "draft sign-off commentary for the <desk> desk"
        )

    def test_empty_input(self) -> None:
        assert normalize_prompt("") == ""
        assert normalize_prompt("   ") == ""


class TestPromptSignature:
    def test_core_property_variants_share_signature(self) -> None:
        a = prompt_signature("Why is there an FX recon break of 100k on EURUSD?")
        b = prompt_signature("why is there an fx recon break of 250k on GBPUSD ?")
        assert a == b
        assert a == "why is there an fx recon break of <num> on <ccy>"

    def test_date_variants_share_signature(self) -> None:
        sigs = {
            prompt_signature("Explain the PnL move on 2026-07-29"),
            prompt_signature("explain the pnl move on 29/07/2026"),
            prompt_signature("Explain the PnL move on July 29"),
        }
        assert sigs == {"explain the pnl move on <date>"}

    def test_id_variants_share_signature(self) -> None:
        a = prompt_signature("What is the status of adjustment ADJ-1234?")
        b = prompt_signature("what is the status of adjustment ADJ-9876 ?")
        assert a == b

    def test_distinct_intents_do_not_collide(self) -> None:
        recon = prompt_signature("Why is there an FX recon break of 100k on EURUSD?")
        commentary = prompt_signature("Draft sign-off commentary for the rates desk")
        assert recon != commentary

    def test_punctuation_is_stripped(self) -> None:
        assert prompt_signature("Show breaks!!!") == prompt_signature("show breaks")
        assert "?" not in prompt_signature("Any breaks today?")

    def test_placeholders_survive_punctuation_stripping(self) -> None:
        sig = prompt_signature("break of 100k on EURUSD on 2026-07-29 ref ADJ-12")
        assert "<num>" in sig
        assert "<ccy>" in sig
        assert "<date>" in sig
        assert "<id>" in sig

    def test_empty_input_gives_empty_signature(self) -> None:
        assert prompt_signature("") == ""
        assert prompt_signature("  \t \n ") == ""
        assert prompt_signature("?!.,") == ""
