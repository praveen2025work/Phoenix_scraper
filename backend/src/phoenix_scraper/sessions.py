"""Derive per-session aggregates from the spans dataframe (Store.spans_frame output)."""

from datetime import UTC, datetime

import pandas as pd

from .models import SessionRecord

_LLM_KIND = "LLM"


def derive_sessions(spans_df: pd.DataFrame) -> list[SessionRecord]:
    """Group spans by session_id and aggregate into SessionRecord objects.

    Rows with a null or empty session_id are dropped. The input frame is never
    mutated. Results are ordered by session start_time.
    """
    if spans_df.empty:
        return []

    session_ids = spans_df["session_id"]
    valid = spans_df.loc[session_ids.notna() & (session_ids != "")]
    if valid.empty:
        return []

    records = [
        _build_record(session_id, group.sort_values("start_time"))
        for session_id, group in valid.groupby("session_id", sort=False)
    ]
    return sorted(records, key=lambda r: r.start_time)


def _build_record(session_id: str, group: pd.DataFrame) -> SessionRecord:
    llm_rows = group.loc[group["span_kind"] == _LLM_KIND]
    user_turns = llm_rows.loc[llm_rows["input_text"].fillna("") != ""]

    non_null_users = group["user_id"].dropna()
    models = group["model_name"].dropna().unique()

    first_prompt = ""
    if not llm_rows.empty:
        first_prompt = str(llm_rows.iloc[0]["input_text"] or "")

    return SessionRecord(
        session_id=str(session_id),
        project=str(group.iloc[0]["project"]),
        user_id=str(non_null_users.iloc[0]) if not non_null_users.empty else None,
        start_time=_to_utc(group["start_time"].min()),
        end_time=_optional_utc(group["end_time"].max()),
        n_traces=int(group["trace_id"].nunique()),
        n_llm_spans=int(len(llm_rows)),
        n_user_turns=int(len(user_turns)),
        total_tokens=int(group["tokens_total"].fillna(0).sum()),
        total_cost_usd=float(group["cost_usd"].fillna(0.0).sum()),
        models=tuple(sorted(str(m) for m in models)),
        first_prompt=first_prompt,
    )


def _to_utc(value: pd.Timestamp) -> datetime:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize(UTC) if ts.tzinfo is None else ts.tz_convert(UTC)
    return ts.to_pydatetime()


def _optional_utc(value: pd.Timestamp | None) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    return _to_utc(value)
