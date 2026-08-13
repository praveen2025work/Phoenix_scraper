"""Deeper analytics over spans: trace routes, question taxonomy, friction, efficiency.

Everything here is pure — DataFrames in, DataFrames out — so it works identically
for the API, exports, and tests. Input frames use the Store.spans_frame() schema.
"""

import re

import pandas as pd
from rapidfuzz import fuzz

from .normalize import prompt_signature

_LLM = "LLM"
_OK = "OK"

# Only explicit failures are errors — OpenTelemetry/Phoenix spans routinely
# carry "UNSET" for uninstrumented statuses, which must not count as errors.
_ERROR_STATUSES = frozenset({"ERROR"})

# Reformulation: consecutive prompts in a session this similar (on the raw,
# unmasked text) mean the user is re-asking / refining. Compared unmasked so
# genuinely different entities (other book, other currency) break the match.
_REFORMULATION_SIMILARITY = 90

# Long route: a cluster whose average spans-per-trace exceeds the overall
# average by this factor burns extra steps for a routine ask — prime skill
# material. Only flagged with enough asks to make the average meaningful.
_LONG_ROUTE_FACTOR = 1.5
_LONG_ROUTE_MIN_ASKS = 3

_QUESTION_WORDS = {
    "why": "why",
    "what": "what",
    "whats": "what",
    "how": "how",
    "when": "when",
    "where": "where",
    "which": "which",
    "who": "who",
}
_CHECK_WORDS = frozenset(
    {"can", "could", "would", "should", "will", "is", "are", "do", "does", "did", "has", "have"}
)
_REQUEST_WORDS = frozenset(
    {
        "show", "give", "list", "export", "send", "get", "pull", "generate",
        "create", "run", "rerun", "compare", "summarize", "summarise", "explain",
        "provide", "book", "check", "find", "download", "fetch", "draft",
        "suggest", "post", "reconcile", "translate", "email", "set", "walk",
        "order", "remind", "write", "build", "update", "calculate", "prepare",
    }
)
_WORD = re.compile(r"[a-z']+")
_WHITESPACE = re.compile(r"\s+")


def error_mask(status_codes: pd.Series) -> pd.Series:
    """Boolean mask of spans whose status is an explicit failure."""
    return status_codes.fillna(_OK).astype(str).str.upper().isin(_ERROR_STATUSES)


def count_reformulations(texts: list[str]) -> int:
    """Consecutive near-identical asks (typo fixes, small edits, re-sends)."""
    normalized = [_WHITESPACE.sub(" ", t.casefold()).strip() for t in texts]
    return sum(
        1
        for previous, current in zip(normalized, normalized[1:], strict=False)
        if previous
        and current
        and fuzz.token_sort_ratio(previous, current) >= _REFORMULATION_SIMILARITY
    )

_ENTITY_FLAGS = {
    "asks_with_amounts": "<num>",
    "asks_with_ccy": "<ccy>",
    "asks_with_books": "<book>",
    "asks_with_dates": "<date>",
    "asks_with_ids": "<id>",
}


def question_type(text: str) -> str:
    """Coarse intent class for one prompt: why/what/how/when/which/check/request/…"""
    words = _WORD.findall(text.casefold())
    if not words:
        return "statement"
    first = words[0].replace("'", "")  # "what's" -> "whats"
    if first in _QUESTION_WORDS:
        return _QUESTION_WORDS[first]
    if first in _CHECK_WORDS:
        return "check"
    if first in _REQUEST_WORDS or (len(words) > 1 and words[0] == "please"):
        return "request"
    if "?" in text:
        return "other_question"
    return "other"


def trace_profiles(spans_df: pd.DataFrame) -> pd.DataFrame:
    """One row per trace: the route the agent took to answer one ask."""
    if spans_df.empty:
        return pd.DataFrame(columns=_TRACE_COLUMNS)
    rows = [
        _trace_row(trace_id, group.sort_values("start_time"))
        for trace_id, group in spans_df.groupby("trace_id", sort=False)
    ]
    df = pd.DataFrame(rows, columns=_TRACE_COLUMNS)
    return df.sort_values("start_time").reset_index(drop=True)


_TRACE_COLUMNS = [
    "trace_id", "session_id", "user_id", "start_time", "n_spans", "n_llm",
    "n_tool", "n_other", "n_errors", "total_tokens", "total_cost_usd",
    "duration_ms", "first_prompt",
]


def _trace_row(trace_id: str, group: pd.DataFrame) -> dict:
    kinds = group["span_kind"].fillna("UNKNOWN")
    n_llm = int((kinds == _LLM).sum())
    n_tool = int((kinds == "TOOL").sum())
    prompts = group.loc[(kinds == _LLM) & (group["input_text"].fillna("") != ""), "input_text"]
    start = group["start_time"].min()
    end = group["end_time"].max()
    duration_ms = None
    if pd.notna(start) and pd.notna(end):
        duration_ms = float((end - start).total_seconds() * 1000.0)
    session_ids = group["session_id"].dropna()
    user_ids = group["user_id"].dropna()
    return {
        "trace_id": str(trace_id),
        "session_id": str(session_ids.iloc[0]) if not session_ids.empty else None,
        "user_id": str(user_ids.iloc[0]) if not user_ids.empty else None,
        "start_time": start,
        "n_spans": int(len(group)),
        "n_llm": n_llm,
        "n_tool": n_tool,
        "n_other": int(len(group)) - n_llm - n_tool,
        "n_errors": int(error_mask(group["status_code"]).sum()),
        "total_tokens": int(group["tokens_total"].fillna(0).sum()),
        "total_cost_usd": float(group["cost_usd"].fillna(0.0).sum()),
        "duration_ms": duration_ms,
        "first_prompt": str(prompts.iloc[0]) if not prompts.empty else "",
    }


def question_taxonomy(spans_df: pd.DataFrame) -> pd.DataFrame:
    """What users ask, grouped by coarse intent — with entity coverage per type."""
    turns = _user_turns(spans_df)
    if turns.empty:
        return pd.DataFrame(columns=_TAXONOMY_COLUMNS)

    work = turns.assign(
        _qtype=turns["input_text"].map(question_type),
        _signature=turns["input_text"].map(prompt_signature),
    )
    rows = []
    for qtype, group in work.groupby("_qtype", sort=False):
        mean_tokens = group["tokens_total"].mean()  # skipna: None when unmeasured
        row = {
            "question_type": qtype,
            "count": int(len(group)),
            "n_sessions": int(group["session_id"].dropna().nunique()),
            "n_users": int(group["user_id"].dropna().nunique()),
            "total_cost_usd": float(group["cost_usd"].fillna(0.0).sum()),
            "avg_tokens": float(mean_tokens) if pd.notna(mean_tokens) else None,
            "example": str(group["input_text"].iloc[0]),
        }
        for column, token in _ENTITY_FLAGS.items():
            row[column] = int(group["_signature"].str.contains(token, regex=False).sum())
        rows.append(row)
    df = pd.DataFrame(rows, columns=_TAXONOMY_COLUMNS)
    return df.sort_values("count", ascending=False).reset_index(drop=True)


_TAXONOMY_COLUMNS = [
    "question_type", "count", "n_sessions", "n_users", "total_cost_usd",
    "avg_tokens", "example", *_ENTITY_FLAGS,
]


def session_friction(spans_df: pd.DataFrame) -> pd.DataFrame:
    """Per-session signals that users aren't getting answers.

    Reformulations (re-asking near-identical questions), error spans, and empty
    responses each raise the friction score; the noisiest sessions come first.
    """
    if spans_df.empty:
        return pd.DataFrame(columns=_FRICTION_COLUMNS)
    valid = spans_df.loc[spans_df["session_id"].notna() & (spans_df["session_id"] != "")]
    if valid.empty:
        return pd.DataFrame(columns=_FRICTION_COLUMNS)

    rows = [
        _friction_row(session_id, group.sort_values("start_time"))
        for session_id, group in valid.groupby("session_id", sort=False)
    ]
    df = pd.DataFrame(rows, columns=_FRICTION_COLUMNS)
    return df.sort_values(
        ["friction_score", "n_turns"], ascending=False
    ).reset_index(drop=True)


_FRICTION_COLUMNS = [
    "session_id", "user_id", "start_time", "n_turns", "n_reformulations",
    "n_errors", "n_empty_responses", "duration_minutes", "total_tokens",
    "total_cost_usd", "friction_score", "first_prompt",
]


def _friction_row(session_id: str, group: pd.DataFrame) -> dict:
    turns = group.loc[
        (group["span_kind"] == _LLM) & (group["input_text"].fillna("") != "")
    ]
    reformulations = count_reformulations(list(turns["input_text"]))
    n_errors = int(error_mask(group["status_code"]).sum())
    n_empty = int((turns["output_text"].fillna("") == "").sum())
    start = group["start_time"].min()
    end = group["end_time"].max()
    duration_minutes = None
    if pd.notna(start) and pd.notna(end):
        duration_minutes = float((end - start).total_seconds() / 60.0)
    user_ids = group["user_id"].dropna()
    return {
        "session_id": str(session_id),
        "user_id": str(user_ids.iloc[0]) if not user_ids.empty else None,
        "start_time": start,
        "n_turns": int(len(turns)),
        "n_reformulations": reformulations,
        "n_errors": n_errors,
        "n_empty_responses": n_empty,
        "duration_minutes": duration_minutes,
        "total_tokens": int(group["tokens_total"].fillna(0).sum()),
        "total_cost_usd": float(group["cost_usd"].fillna(0.0).sum()),
        "friction_score": 2 * reformulations + 2 * n_errors + n_empty,
        "first_prompt": str(turns["input_text"].iloc[0]) if not turns.empty else "",
    }


def cluster_efficiency(
    spans_df: pd.DataFrame, clusters_df: pd.DataFrame, members_df: pd.DataFrame
) -> pd.DataFrame:
    """Per prompt cluster: how hard the agent works to answer it.

    route_len_avg is the average spans-per-trace across the cluster's asks; a
    cluster flagged long_route answers a routine question with far more steps
    than the average trace — the strongest signal that a dedicated skill (or a
    fix to an ineffective one) would shorten the route. opportunity_score
    (count x tokens_per_ask) ranks where that saving is largest. Callers must
    pass the SAME span population the clusters were built from, or route
    lengths will describe a different corpus than the counts.
    """
    if spans_df.empty or clusters_df.empty or members_df.empty:
        return pd.DataFrame(columns=_EFFICIENCY_COLUMNS)

    traces = trace_profiles(spans_df).set_index("trace_id")
    baseline_route = float(traces["n_spans"].mean())  # same statistic as route_len_avg
    span_to_trace = spans_df.drop_duplicates("span_id").set_index("span_id")["trace_id"]

    rows = []
    for cluster in clusters_df.to_dict("records"):
        member_ids = members_df.loc[
            members_df["cluster_id"] == cluster["cluster_id"], "span_id"
        ]
        trace_ids = span_to_trace.reindex(member_ids).dropna().unique()
        cluster_traces = traces.loc[traces.index.intersection(trace_ids)]
        if cluster_traces.empty:
            continue
        route_len = float(cluster_traces["n_spans"].mean())
        tokens_per_ask = float(cluster_traces["total_tokens"].mean())
        count = int(cluster.get("count", len(member_ids)))
        rows.append(
            {
                "cluster_id": cluster["cluster_id"],
                "representative": cluster.get("representative", ""),
                "count": count,
                "route_len_avg": route_len,
                "baseline_route": baseline_route,
                "long_route": bool(
                    count >= _LONG_ROUTE_MIN_ASKS
                    and route_len > baseline_route * _LONG_ROUTE_FACTOR
                ),
                "tokens_per_ask": tokens_per_ask,
                "error_rate": float((cluster_traces["n_errors"] > 0).mean()),
                "total_cost_usd": float(cluster.get("total_cost_usd", 0.0) or 0.0),
                "avg_latency_ms": cluster.get("avg_latency_ms"),
                "opportunity_score": float(count * tokens_per_ask),
            }
        )
    df = pd.DataFrame(rows, columns=_EFFICIENCY_COLUMNS)
    if df.empty:
        return df
    return df.sort_values("opportunity_score", ascending=False).reset_index(drop=True)


_EFFICIENCY_COLUMNS = [
    "cluster_id", "representative", "count", "route_len_avg", "baseline_route",
    "long_route", "tokens_per_ask", "error_rate", "total_cost_usd",
    "avg_latency_ms", "opportunity_score",
]


def skill_health(efficiency_df: pd.DataFrame, matches_df: pd.DataFrame) -> pd.DataFrame:
    """Per matched skill: is the agent still taking long routes despite it?

    status 'review' means at least one cluster matched to this skill is flagged
    long_route — the skill exists but isn't shortening the work (wrong content,
    stale instructions, or the agent isn't picking it up).
    """
    if efficiency_df.empty or matches_df.empty:
        return pd.DataFrame(columns=_HEALTH_COLUMNS)
    # matches_frame() may carry its own count/representative columns; keep only
    # the identity columns so the merge never suffixes the efficiency ones.
    matches = matches_df.loc[:, ["cluster_id", "skill_name", "score"]]
    joined = matches.merge(efficiency_df, on="cluster_id", how="inner")
    if joined.empty:
        return pd.DataFrame(columns=_HEALTH_COLUMNS)

    rows = []
    for skill_name, group in joined.groupby("skill_name", sort=False):
        asks = int(group["count"].sum())
        long_asks = int(group.loc[group["long_route"], "count"].sum())
        rows.append(
            {
                "skill_name": str(skill_name),
                "n_clusters": int(group["cluster_id"].nunique()),
                "n_asks": asks,
                "avg_route_len": float(group["route_len_avg"].mean()),
                "avg_tokens_per_ask": float(group["tokens_per_ask"].mean()),
                "error_rate": float(group["error_rate"].mean()),
                "match_score": float(group["score"].max()),
                # review only when the MAJORITY of this skill's asks take long
                # routes — one unlucky cluster must not redden the skill.
                "status": "review" if asks and long_asks * 2 > asks else "effective",
            }
        )
    df = pd.DataFrame(rows, columns=_HEALTH_COLUMNS)
    return df.sort_values("n_asks", ascending=False).reset_index(drop=True)


_HEALTH_COLUMNS = [
    "skill_name", "n_clusters", "n_asks", "avg_route_len", "avg_tokens_per_ask",
    "error_rate", "match_score", "status",
]


def _user_turns(spans_df: pd.DataFrame) -> pd.DataFrame:
    if spans_df.empty:
        return spans_df
    return spans_df.loc[
        (spans_df["span_kind"] == _LLM) & (spans_df["input_text"].fillna("") != "")
    ]
