"""Token-based cost estimation and cost aggregation over span frames."""

from pathlib import Path

import pandas as pd
import yaml

from .models import ModelPricing

_SUMMARY_METRICS = ["n_spans", "total_tokens", "total_cost_usd"]
_ALLOWED_GROUP_BY = frozenset(
    {"model_name", "workflow_stage", "asset_class", "user_id", "session_id"}
)


def load_pricing(path: Path) -> tuple[dict[str, ModelPricing], ModelPricing]:
    """Parse pricing.yaml into ({model_prefix: ModelPricing}, default_pricing)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "default" not in raw:
        raise ValueError(f"Invalid pricing file (missing 'default'): {path}")
    models = {
        str(name): ModelPricing(**spec) for name, spec in (raw.get("models") or {}).items()
    }
    return models, ModelPricing(**raw["default"])


def price_for(
    model_name: str | None,
    pricing: dict[str, ModelPricing],
    default: ModelPricing,
) -> ModelPricing:
    """Longest pricing key that is a case-insensitive prefix of model_name, else default."""
    if not model_name:
        return default
    lowered = model_name.lower()
    best_key: str | None = None
    for key in pricing:
        if lowered.startswith(key.lower()) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return pricing[best_key] if best_key is not None else default


def compute_span_costs(
    spans_df: pd.DataFrame,
    pricing: dict[str, ModelPricing],
    default: ModelPricing,
) -> dict[str, float]:
    """Estimate cost_usd for LLM rows missing it; returns {span_id: cost} for new rows only."""
    if spans_df.empty:
        return {}
    costs: dict[str, float] = {}
    for row in spans_df.itertuples(index=False):
        if getattr(row, "span_kind", None) != "LLM":
            continue
        if not pd.isna(getattr(row, "cost_usd", None)):
            continue  # existing cost is authoritative — never overwrite
        tokens_prompt = getattr(row, "tokens_prompt", None)
        tokens_completion = getattr(row, "tokens_completion", None)
        if pd.isna(tokens_prompt) or pd.isna(tokens_completion):
            continue
        model_name = getattr(row, "model_name", None)
        p = price_for(None if pd.isna(model_name) else model_name, pricing, default)
        costs[row.span_id] = (
            float(tokens_prompt) / 1000.0 * p.input_per_1k
            + float(tokens_completion) / 1000.0 * p.output_per_1k
        )
    return costs


def cost_summary(spans_df: pd.DataFrame, group_by: list[str]) -> pd.DataFrame:
    """Aggregate span counts, tokens, and cost per group, sorted by total cost descending."""
    if not group_by:
        raise ValueError("group_by must contain at least one column")
    invalid = [c for c in group_by if c not in _ALLOWED_GROUP_BY]
    if invalid:
        raise ValueError(
            f"Invalid group_by columns {invalid}; allowed: {sorted(_ALLOWED_GROUP_BY)}"
        )
    out_columns = [*group_by, *_SUMMARY_METRICS]
    if spans_df.empty:
        return pd.DataFrame(columns=out_columns)

    work = spans_df.assign(
        total_tokens=spans_df["tokens_total"].fillna(0).astype(int),
        total_cost_usd=spans_df["cost_usd"].fillna(0.0),
    )
    summary = (
        work.groupby(group_by, dropna=False)
        .agg(
            n_spans=("span_id", "count"),
            total_tokens=("total_tokens", "sum"),
            total_cost_usd=("total_cost_usd", "sum"),
        )
        .reset_index()
        .sort_values("total_cost_usd", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    return summary[out_columns]
