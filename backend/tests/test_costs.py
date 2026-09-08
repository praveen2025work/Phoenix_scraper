"""Tests for costs.py: pricing lookup, span cost computation, and cost summaries."""

from pathlib import Path

import pandas as pd
import pytest

from phoenix_scraper.costs import (
    compute_span_costs,
    cost_summary,
    load_pricing,
    price_for,
)
from phoenix_scraper.models import ModelPricing

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICING_PATH = REPO_ROOT / "config" / "pricing.yaml"


@pytest.fixture()
def pricing() -> tuple[dict[str, ModelPricing], ModelPricing]:
    return load_pricing(PRICING_PATH)


def _spans_df(rows: list[dict]) -> pd.DataFrame:
    """Build a frame shaped like Store.spans_frame() output."""
    defaults = {
        "span_id": "s-0",
        "session_id": "sess-0",
        "user_id": "analyst-0",
        "span_kind": "LLM",
        "model_name": "us.anthropic.claude-sonnet-4-6",
        "workflow_stage": "fobo_recon",
        "asset_class": "fx",
        "tokens_prompt": None,
        "tokens_completion": None,
        "tokens_total": None,
        "cost_usd": None,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


# ---- load_pricing -----------------------------------------------------------


class TestLoadPricing:
    def test_returns_models_and_default(self, pricing) -> None:
        models, default = pricing
        assert isinstance(default, ModelPricing)
        assert default.input_per_1k == 0.003
        assert default.output_per_1k == 0.015
        assert "us.anthropic.claude-sonnet-4-6" in models
        assert models["anthropic.claude-3-5-haiku"].input_per_1k == 0.0008

    def test_all_values_are_model_pricing(self, pricing) -> None:
        models, _ = pricing
        assert all(isinstance(v, ModelPricing) for v in models.values())
        assert len(models) == 5


# ---- price_for --------------------------------------------------------------


class TestPriceFor:
    def test_exact_prefix_match(self, pricing) -> None:
        models, default = pricing
        p = price_for("us.anthropic.claude-sonnet-4-6-v1:0", models, default)
        assert p == models["us.anthropic.claude-sonnet-4-6"]

    def test_most_specific_prefix_wins(self) -> None:
        default = ModelPricing(input_per_1k=1.0, output_per_1k=1.0)
        models = {
            "anthropic.claude": ModelPricing(input_per_1k=0.1, output_per_1k=0.2),
            "anthropic.claude-3-5-haiku": ModelPricing(
                input_per_1k=0.0008, output_per_1k=0.004
            ),
        }
        p = price_for("anthropic.claude-3-5-haiku-20241022", models, default)
        assert p.input_per_1k == 0.0008
        # shorter prefix still catches other variants
        p2 = price_for("anthropic.claude-opus", models, default)
        assert p2.input_per_1k == 0.1

    def test_case_insensitive(self, pricing) -> None:
        models, default = pricing
        p = price_for("US.Anthropic.Claude-Sonnet-4-6", models, default)
        assert p == models["us.anthropic.claude-sonnet-4-6"]

    def test_none_model_falls_back_to_default(self, pricing) -> None:
        models, default = pricing
        assert price_for(None, models, default) is default

    def test_unknown_model_falls_back_to_default(self, pricing) -> None:
        models, default = pricing
        assert price_for("gpt-4o", models, default) is default

    def test_empty_model_falls_back_to_default(self, pricing) -> None:
        models, default = pricing
        assert price_for("", models, default) is default


# ---- compute_span_costs -----------------------------------------------------


class TestComputeSpanCosts:
    def test_computes_cost_from_tokens(self, pricing) -> None:
        models, default = pricing
        df = _spans_df(
            [{"span_id": "s-1", "tokens_prompt": 200, "tokens_completion": 80}]
        )
        costs = compute_span_costs(df, models, default)
        assert costs == {"s-1": pytest.approx(200 / 1000 * 0.003 + 80 / 1000 * 0.015)}

    def test_existing_cost_never_overwritten(self, pricing) -> None:
        models, default = pricing
        df = _spans_df(
            [
                {
                    "span_id": "s-1",
                    "tokens_prompt": 200,
                    "tokens_completion": 80,
                    "cost_usd": 0.42,
                }
            ]
        )
        assert compute_span_costs(df, models, default) == {}

    def test_rows_without_tokens_skipped(self, pricing) -> None:
        models, default = pricing
        df = _spans_df(
            [
                {"span_id": "s-1"},  # no tokens at all
                {"span_id": "s-2", "tokens_prompt": 100},  # missing completion
                {"span_id": "s-3", "tokens_completion": 50},  # missing prompt
            ]
        )
        assert compute_span_costs(df, models, default) == {}

    def test_non_llm_rows_skipped(self, pricing) -> None:
        models, default = pricing
        df = _spans_df(
            [
                {
                    "span_id": "s-1",
                    "span_kind": "TOOL",
                    "tokens_prompt": 100,
                    "tokens_completion": 50,
                }
            ]
        )
        assert compute_span_costs(df, models, default) == {}

    def test_unknown_model_uses_default_pricing(self) -> None:
        default = ModelPricing(input_per_1k=0.01, output_per_1k=0.02)
        df = _spans_df(
            [
                {
                    "span_id": "s-1",
                    "model_name": "mystery-model",
                    "tokens_prompt": 1000,
                    "tokens_completion": 500,
                }
            ]
        )
        costs = compute_span_costs(df, {}, default)
        assert costs == {"s-1": pytest.approx(1000 / 1000 * 0.01 + 500 / 1000 * 0.02)}

    def test_empty_frame(self, pricing) -> None:
        models, default = pricing
        assert compute_span_costs(pd.DataFrame(), models, default) == {}

    def test_input_frame_not_mutated(self, pricing) -> None:
        models, default = pricing
        df = _spans_df(
            [{"span_id": "s-1", "tokens_prompt": 200, "tokens_completion": 80}]
        )
        before = df.copy(deep=True)
        compute_span_costs(df, models, default)
        pd.testing.assert_frame_equal(df, before)


# ---- cost_summary -----------------------------------------------------------


class TestCostSummary:
    def _frame(self) -> pd.DataFrame:
        return _spans_df(
            [
                {"span_id": "s-1", "model_name": "m-a", "tokens_total": 100, "cost_usd": 0.5},
                {"span_id": "s-2", "model_name": "m-a", "tokens_total": 200, "cost_usd": 0.7},
                {"span_id": "s-3", "model_name": "m-b", "tokens_total": 300, "cost_usd": 2.0},
                {"span_id": "s-4", "model_name": "m-c", "tokens_total": None, "cost_usd": None},
            ]
        )

    def test_group_by_model_sorted_by_cost_desc(self) -> None:
        out = cost_summary(self._frame(), ["model_name"])
        assert list(out.columns) == ["model_name", "n_spans", "total_tokens", "total_cost_usd"]
        assert out["model_name"].tolist() == ["m-b", "m-a", "m-c"]
        row_a = out[out["model_name"] == "m-a"].iloc[0]
        assert row_a["n_spans"] == 2
        assert row_a["total_tokens"] == 300
        assert row_a["total_cost_usd"] == pytest.approx(1.2)

    def test_null_tokens_and_costs_treated_as_zero(self) -> None:
        out = cost_summary(self._frame(), ["model_name"])
        row_c = out[out["model_name"] == "m-c"].iloc[0]
        assert row_c["n_spans"] == 1
        assert row_c["total_tokens"] == 0
        assert row_c["total_cost_usd"] == 0.0

    def test_multi_column_grouping(self) -> None:
        df = _spans_df(
            [
                {"span_id": "s-1", "workflow_stage": "plex", "asset_class": "fx",
                 "tokens_total": 10, "cost_usd": 0.1},
                {"span_id": "s-2", "workflow_stage": "plex", "asset_class": "rates",
                 "tokens_total": 20, "cost_usd": 0.9},
            ]
        )
        out = cost_summary(df, ["workflow_stage", "asset_class"])
        assert list(out.columns) == [
            "workflow_stage", "asset_class", "n_spans", "total_tokens", "total_cost_usd",
        ]
        assert out.iloc[0]["asset_class"] == "rates"

    def test_invalid_group_by_raises(self) -> None:
        with pytest.raises(ValueError):
            cost_summary(self._frame(), ["not_a_column"])

    def test_empty_group_by_raises(self) -> None:
        with pytest.raises(ValueError):
            cost_summary(self._frame(), [])

    def test_empty_frame_returns_empty_with_columns(self) -> None:
        out = cost_summary(pd.DataFrame(), ["model_name"])
        assert out.empty
        assert list(out.columns) == ["model_name", "n_spans", "total_tokens", "total_cost_usd"]

    def test_input_frame_not_mutated(self) -> None:
        df = self._frame()
        before = df.copy(deep=True)
        cost_summary(df, ["model_name"])
        pd.testing.assert_frame_equal(df, before)
