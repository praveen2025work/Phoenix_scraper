"""What the LLM/agent actually does: tools, models, flows, and dimensions."""

import pandas as pd

from .insights import error_mask

_LLM = "LLM"
_MAX_FLOW_STEPS = 12
_UNATTRIBUTED = "(unattributed)"


def tool_usage(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Per tool: call volume, failure rate, latency — the agent's working set."""
    if spans_df.empty:
        return pd.DataFrame(columns=_TOOL_COLUMNS)
    tools = spans_df.loc[spans_df["span_kind"] == "TOOL"]
    if tools.empty:
        return pd.DataFrame(columns=_TOOL_COLUMNS)

    rows = []
    for name, group in tools.groupby(tools["name"].fillna("(unnamed)"), sort=False):
        latencies = group["latency_ms"].dropna()
        rows.append(
            {
                "tool": str(name),
                "n_calls": int(len(group)),
                "n_traces": int(group["trace_id"].nunique()),
                "error_rate": float(error_mask(group["status_code"]).mean()),
                "avg_latency_ms": float(latencies.mean()) if not latencies.empty else None,
                "p95_latency_ms": float(latencies.quantile(0.95))
                if not latencies.empty
                else None,
            }
        )
    df = pd.DataFrame(rows, columns=_TOOL_COLUMNS)
    return df.sort_values("n_calls", ascending=False).reset_index(drop=True)


_TOOL_COLUMNS = ["tool", "n_calls", "n_traces", "error_rate", "avg_latency_ms",
                 "p95_latency_ms"]


def model_usage(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Per model: calls, tokens in/out, cost, latency, errors."""
    if spans_df.empty:
        return pd.DataFrame(columns=_MODEL_COLUMNS)
    llm = spans_df.loc[spans_df["model_name"].notna() & (spans_df["model_name"] != "")]
    if llm.empty:
        return pd.DataFrame(columns=_MODEL_COLUMNS)

    rows = []
    for model, group in llm.groupby("model_name", sort=False):
        latencies = group["latency_ms"].dropna()
        rows.append(
            {
                "model": str(model),
                "n_calls": int(len(group)),
                "tokens_in": int(group["tokens_prompt"].fillna(0).sum()),
                "tokens_out": int(group["tokens_completion"].fillna(0).sum()),
                "total_tokens": int(group["tokens_total"].fillna(0).sum()),
                "total_cost_usd": float(group["cost_usd"].fillna(0.0).sum()),
                "avg_latency_ms": float(latencies.mean()) if not latencies.empty else None,
                "error_rate": float(error_mask(group["status_code"]).mean()),
            }
        )
    df = pd.DataFrame(rows, columns=_MODEL_COLUMNS)
    return df.sort_values("n_calls", ascending=False).reset_index(drop=True)


_MODEL_COLUMNS = ["model", "n_calls", "tokens_in", "tokens_out", "total_tokens",
                  "total_cost_usd", "avg_latency_ms", "error_rate"]


def agent_flows(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Common step sequences per trace — what the agent does to answer an ask.

    Consecutive repeats collapse with a count ("LLM → TOOL ×3 → LLM") so flows
    group by shape rather than exact length.
    """
    if spans_df.empty:
        return pd.DataFrame(columns=_FLOW_COLUMNS)

    per_trace = []
    for trace_id, group in spans_df.groupby("trace_id", sort=False):
        ordered = group.sort_values("start_time")
        flow = _flow_signature(list(ordered["span_kind"].fillna("UNKNOWN")))
        prompts = ordered.loc[
            (ordered["span_kind"] == _LLM) & (ordered["input_text"].fillna("") != ""),
            "input_text",
        ]
        per_trace.append(
            {
                "trace_id": trace_id,
                "flow": flow,
                "n_spans": int(len(group)),
                "total_tokens": int(group["tokens_total"].fillna(0).sum()),
                "prompt": str(prompts.iloc[0]) if not prompts.empty else "",
            }
        )
    traces = pd.DataFrame(per_trace)
    rows = []
    for flow, group in traces.groupby("flow", sort=False):
        examples = group.loc[group["prompt"] != "", "prompt"]
        rows.append(
            {
                "flow": str(flow),
                "n_traces": int(len(group)),
                "avg_steps": float(group["n_spans"].mean()),
                "avg_tokens": float(group["total_tokens"].mean()),
                "example_prompt": str(examples.iloc[0]) if not examples.empty else "",
            }
        )
    df = pd.DataFrame(rows, columns=_FLOW_COLUMNS)
    return df.sort_values("n_traces", ascending=False).reset_index(drop=True)


_FLOW_COLUMNS = ["flow", "n_traces", "avg_steps", "avg_tokens", "example_prompt"]


def _flow_signature(kinds: list[str]) -> str:
    collapsed: list[tuple[str, int]] = []
    for kind in kinds:
        if collapsed and collapsed[-1][0] == kind:
            collapsed[-1] = (kind, collapsed[-1][1] + 1)
        else:
            collapsed.append((kind, 1))
    parts = [kind if n == 1 else f"{kind} ×{n}" for kind, n in collapsed[:_MAX_FLOW_STEPS]]
    if len(collapsed) > _MAX_FLOW_STEPS:
        parts.append("…")
    return " → ".join(parts)


def stage_asset_breakdown(spans_df: pd.DataFrame) -> pd.DataFrame:
    """workflow_stage x asset_class rollup of asks, tokens, and cost."""
    if spans_df.empty:
        return pd.DataFrame(columns=_BREAKDOWN_COLUMNS)
    turns = spans_df.loc[
        (spans_df["span_kind"] == _LLM) & (spans_df["input_text"].fillna("") != "")
    ]
    if turns.empty:
        return pd.DataFrame(columns=_BREAKDOWN_COLUMNS)

    work = turns.assign(
        workflow_stage=turns["workflow_stage"].fillna(_UNATTRIBUTED).replace("", _UNATTRIBUTED),
        asset_class=turns["asset_class"].fillna(_UNATTRIBUTED).replace("", _UNATTRIBUTED),
    )
    df = (
        work.groupby(["workflow_stage", "asset_class"], sort=False)
        .agg(
            n_asks=("span_id", "count"),
            n_sessions=("session_id", "nunique"),
            n_users=("user_id", "nunique"),
            total_tokens=("tokens_total", lambda s: int(s.fillna(0).sum())),
            total_cost_usd=("cost_usd", lambda s: float(s.fillna(0.0).sum())),
        )
        .reset_index()
    )
    return df.sort_values("n_asks", ascending=False).reset_index(drop=True)


_BREAKDOWN_COLUMNS = ["workflow_stage", "asset_class", "n_asks", "n_sessions",
                      "n_users", "total_tokens", "total_cost_usd"]
