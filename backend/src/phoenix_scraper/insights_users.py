"""Per-user analytics: who asks what, how often, and with how much friction."""

from collections import Counter

import pandas as pd

from .insights import count_reformulations, error_mask, question_type
from .normalize import prompt_signature

_LLM = "LLM"
_TOP_INTENTS = 3
_TOP_PROMPTS = 3


def user_profiles(spans_df: pd.DataFrame) -> pd.DataFrame:
    """One row per user: activity, spend, friction, and what they ask about."""
    if spans_df.empty:
        return pd.DataFrame(columns=_PROFILE_COLUMNS)
    valid = spans_df.loc[spans_df["user_id"].notna() & (spans_df["user_id"] != "")]
    if valid.empty:
        return pd.DataFrame(columns=_PROFILE_COLUMNS)

    rows = [
        _profile_row(user_id, group.sort_values("start_time"))
        for user_id, group in valid.groupby("user_id", sort=False)
    ]
    df = pd.DataFrame(rows, columns=_PROFILE_COLUMNS)
    return df.sort_values("n_asks", ascending=False).reset_index(drop=True)


_PROFILE_COLUMNS = [
    "user_id", "n_asks", "n_sessions", "n_traces", "n_reformulations", "n_errors",
    "active_days", "first_seen", "last_seen", "total_tokens", "total_cost_usd",
    "avg_route_len", "top_intents", "top_prompts", "models",
]


def _profile_row(user_id: str, group: pd.DataFrame) -> dict:
    turns = group.loc[
        (group["span_kind"] == _LLM) & (group["input_text"].fillna("") != "")
    ]
    intents = Counter(question_type(t) for t in turns["input_text"])
    prompts = Counter(
        sig for sig in (prompt_signature(t) for t in turns["input_text"]) if sig
    )
    reformulations = _count_reformulations(turns)
    route_lens = group.groupby("trace_id")["span_id"].count()
    return {
        "user_id": str(user_id),
        "n_asks": int(len(turns)),
        "n_sessions": int(group["session_id"].dropna().nunique()),
        "n_traces": int(group["trace_id"].nunique()),
        "n_reformulations": reformulations,
        "n_errors": int(error_mask(group["status_code"]).sum()),
        "active_days": int(group["start_time"].dt.date.nunique()),
        "first_seen": group["start_time"].min(),
        "last_seen": group["start_time"].max(),
        "total_tokens": int(group["tokens_total"].fillna(0).sum()),
        "total_cost_usd": float(group["cost_usd"].fillna(0.0).sum()),
        "avg_route_len": float(route_lens.mean()) if not route_lens.empty else None,
        "top_intents": ", ".join(name for name, _ in intents.most_common(_TOP_INTENTS)),
        "top_prompts": " | ".join(name for name, _ in prompts.most_common(_TOP_PROMPTS)),
        "models": ", ".join(sorted(group["model_name"].dropna().unique())),
    }


def _count_reformulations(turns: pd.DataFrame) -> int:
    """Consecutive near-identical asks within the same session."""
    return sum(
        count_reformulations(list(session_turns.sort_values("start_time")["input_text"]))
        for _, session_turns in turns.groupby("session_id", sort=False)
    )


def user_question_matrix(spans_df: pd.DataFrame) -> pd.DataFrame:
    """user x question_type counts — which intents each user leans on."""
    if spans_df.empty:
        return pd.DataFrame(columns=["user_id", "question_type", "count"])
    turns = spans_df.loc[
        (spans_df["span_kind"] == _LLM)
        & (spans_df["input_text"].fillna("") != "")
        & spans_df["user_id"].notna()
    ]
    if turns.empty:
        return pd.DataFrame(columns=["user_id", "question_type", "count"])
    work = turns.assign(question_type=turns["input_text"].map(question_type))
    df = (
        work.groupby(["user_id", "question_type"], sort=False)
        .size()
        .reset_index(name="count")
    )
    return df.sort_values(
        ["user_id", "count"], ascending=[True, False]
    ).reset_index(drop=True)


def daily_activity(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Asks, sessions, users, tokens, and cost per calendar day (UTC)."""
    if spans_df.empty:
        return pd.DataFrame(
            columns=["day", "n_asks", "n_sessions", "n_users", "total_tokens",
                     "total_cost_usd"]
        )
    turns = spans_df.loc[
        (spans_df["span_kind"] == _LLM) & (spans_df["input_text"].fillna("") != "")
    ]
    source = turns if not turns.empty else spans_df
    work = source.assign(day=source["start_time"].dt.date)
    df = (
        work.groupby("day")
        .agg(
            n_asks=("span_id", "count"),
            n_sessions=("session_id", "nunique"),
            n_users=("user_id", "nunique"),
            total_tokens=("tokens_total", lambda s: int(s.fillna(0).sum())),
            total_cost_usd=("cost_usd", lambda s: float(s.fillna(0.0).sum())),
        )
        .reset_index()
    )
    df["day"] = df["day"].astype(str)
    return df.sort_values("day").reset_index(drop=True)
