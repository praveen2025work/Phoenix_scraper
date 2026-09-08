"""Rollups over span evaluations: is the agent answering well, and where isn't it?

Pure DataFrame in / DataFrame out, like the other insights modules. Input is the
:meth:`Store.evaluations_frame` schema — one row per (span, check) joined to the
span's dimensions — so every rollup slices by user, model, stage and date for
free.

The unit of measurement throughout is the **check**: a span is evaluated once per
applicable check, and ``fail_rate`` is failed checks over applicable checks. A
check that did not apply to a span contributes nothing either way, so adding a
narrow check (JSON validity, which only fires on structured answers) never
dilutes the overall numbers.
"""

import pandas as pd

from .evaluations import PASS_SCORE

_UNATTRIBUTED = "(unattributed)"
_EXPLANATION_PREVIEW_CHARS = 200


def with_pass_flag(evals_df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived ``passed`` column. Unscored annotations count as passing.

    A HUMAN annotation pulled from Phoenix often carries only a label ("note",
    "reviewed") with no score; treating those as failures would invent problems.
    """
    if evals_df.empty:
        return evals_df.assign(passed=pd.Series(dtype=bool))
    scores = pd.to_numeric(evals_df["score"], errors="coerce")
    return evals_df.assign(passed=scores.fillna(1.0) >= PASS_SCORE)


def quality_summary(evals_df: pd.DataFrame) -> pd.DataFrame:
    """Per check: how often it applied, how often it failed, and a failing example.

    This is the validation scoreboard — the answer to "what is actually wrong
    with our LLM's answers and our users' prompts".
    """
    if evals_df.empty:
        return pd.DataFrame(columns=_SUMMARY_COLUMNS)
    work = with_pass_flag(evals_df)
    rows = []
    for (name, source), group in work.groupby(["name", "source"], sort=False):
        failed = group.loc[~group["passed"]]
        scores = pd.to_numeric(group["score"], errors="coerce").dropna()
        rows.append(
            {
                "check": str(name),
                "target": _mode(group["target"]),
                "annotator_kind": _mode(group["annotator_kind"]),
                "source": str(source),
                "n_evaluated": int(len(group)),
                "n_failed": int(len(failed)),
                "fail_rate": float((~group["passed"]).mean()),
                "avg_score": float(scores.mean()) if not scores.empty else None,
                "n_users_affected": int(failed["user_id"].dropna().nunique()),
                "n_sessions_affected": int(failed["session_id"].dropna().nunique()),
                "top_label": _mode(failed["label"]) if not failed.empty else "",
                "example": _preview(failed["explanation"]) if not failed.empty else "",
            }
        )
    df = pd.DataFrame(rows, columns=_SUMMARY_COLUMNS)
    return df.sort_values(
        ["n_failed", "fail_rate"], ascending=False
    ).reset_index(drop=True)


_SUMMARY_COLUMNS = [
    "check", "target", "annotator_kind", "source", "n_evaluated", "n_failed",
    "fail_rate", "avg_score", "n_users_affected", "n_sessions_affected",
    "top_label", "example",
]


def quality_by_dimension(evals_df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Fail rates grouped by any span dimension (user_id, model_name, stage, …).

    One function rather than three near-identical ones: the API exposes it as
    per-user and per-model panels, and it takes any column the join carries.
    """
    if evals_df.empty or column not in evals_df.columns:
        return pd.DataFrame(columns=_dimension_columns(column))
    work = with_pass_flag(evals_df)
    work = work.assign(
        **{column: work[column].fillna(_UNATTRIBUTED).replace("", _UNATTRIBUTED)}
    )
    rows = []
    for value, group in work.groupby(column, sort=False):
        failed = group.loc[~group["passed"]]
        prompt_failures = failed.loc[failed["target"] == "prompt"]
        output_failures = failed.loc[failed["target"] != "prompt"]
        rows.append(
            {
                column: str(value),
                "n_spans": int(group["span_id"].nunique()),
                "n_evaluated": int(len(group)),
                "n_failed": int(len(failed)),
                "fail_rate": float((~group["passed"]).mean()),
                "n_spans_failed": int(failed["span_id"].nunique()),
                "n_output_issues": int(len(output_failures)),
                "n_prompt_issues": int(len(prompt_failures)),
                "top_issues": _top_labels(failed["name"]),
            }
        )
    df = pd.DataFrame(rows, columns=_dimension_columns(column))
    return df.sort_values(
        ["n_failed", "n_evaluated"], ascending=False
    ).reset_index(drop=True)


def _dimension_columns(column: str) -> list[str]:
    return [
        column, "n_spans", "n_evaluated", "n_failed", "fail_rate", "n_spans_failed",
        "n_output_issues", "n_prompt_issues", "top_issues",
    ]


def failing_spans(evals_df: pd.DataFrame, limit: int = 200) -> pd.DataFrame:
    """The spans that failed a check, with the prompt, the answer, and why.

    The workbench view: everything an analyst needs to confirm or dismiss a
    finding without leaving the page or opening Phoenix.
    """
    if evals_df.empty:
        return pd.DataFrame(columns=_FAILING_COLUMNS)
    work = with_pass_flag(evals_df)
    failed = work.loc[~work["passed"]]
    if failed.empty:
        return pd.DataFrame(columns=_FAILING_COLUMNS)

    rows = []
    for span_id, group in failed.groupby("span_id", sort=False):
        first = group.iloc[0]
        scores = pd.to_numeric(group["score"], errors="coerce").dropna()
        rows.append(
            {
                "span_id": str(span_id),
                "start_time": first["start_time"],
                "user_id": _none_if_blank(first.get("user_id")),
                "session_id": _none_if_blank(first.get("session_id")),
                "model_name": _none_if_blank(first.get("model_name")),
                "workflow_stage": _none_if_blank(first.get("workflow_stage")),
                "n_failed_checks": int(len(group)),
                "failed_checks": ", ".join(sorted(group["name"].astype(str).unique())),
                "labels": ", ".join(sorted(group["label"].astype(str).unique())),
                "worst_score": float(scores.min()) if not scores.empty else None,
                "explanations": " | ".join(group["explanation"].astype(str)),
                "input_text": str(first.get("input_text") or ""),
                "output_text": str(first.get("output_text") or ""),
            }
        )
    df = pd.DataFrame(rows, columns=_FAILING_COLUMNS)
    return (
        df.sort_values(["n_failed_checks", "start_time"], ascending=[False, False])
        .head(limit)
        .reset_index(drop=True)
    )


_FAILING_COLUMNS = [
    "span_id", "start_time", "user_id", "session_id", "model_name",
    "workflow_stage", "n_failed_checks", "failed_checks", "labels", "worst_score",
    "explanations", "input_text", "output_text",
]


def quality_by_cluster(
    evals_df: pd.DataFrame, clusters_df: pd.DataFrame, members_df: pd.DataFrame
) -> pd.DataFrame:
    """Which prompt patterns the agent answers badly.

    The join that makes validation actionable for this tool's purpose: a frequent
    ask with a high failure rate is the strongest possible case for a new skill —
    it is not merely expensive (which ``cluster_efficiency`` already ranks), it is
    being answered *wrong*. ``priority`` is failed checks weighted by how many
    people hit them.
    """
    if evals_df.empty or clusters_df.empty or members_df.empty:
        return pd.DataFrame(columns=_CLUSTER_COLUMNS)
    work = with_pass_flag(evals_df).merge(members_df, on="span_id", how="inner")
    if work.empty:
        return pd.DataFrame(columns=_CLUSTER_COLUMNS)
    representatives = clusters_df.set_index("cluster_id")

    rows = []
    for cluster_id, group in work.groupby("cluster_id", sort=False):
        if cluster_id not in representatives.index:
            continue
        cluster = representatives.loc[cluster_id]
        failed = group.loc[~group["passed"]]
        n_spans = int(group["span_id"].nunique())
        n_spans_failed = int(failed["span_id"].nunique())
        rows.append(
            {
                "cluster_id": str(cluster_id),
                "representative": str(cluster.get("representative", "")),
                "count": int(cluster.get("count", n_spans)),
                "n_spans_evaluated": n_spans,
                "n_spans_failed": n_spans_failed,
                "span_fail_rate": float(n_spans_failed / n_spans) if n_spans else 0.0,
                "n_failed_checks": int(len(failed)),
                "n_users_affected": int(failed["user_id"].dropna().nunique()),
                "top_issues": _top_labels(failed["name"]),
                "priority": float(
                    n_spans_failed * max(1, int(failed["user_id"].dropna().nunique()))
                ),
            }
        )
    df = pd.DataFrame(rows, columns=_CLUSTER_COLUMNS)
    if df.empty:
        return df
    return df.sort_values(
        ["priority", "n_spans_failed"], ascending=False
    ).reset_index(drop=True)


_CLUSTER_COLUMNS = [
    "cluster_id", "representative", "count", "n_spans_evaluated", "n_spans_failed",
    "span_fail_rate", "n_failed_checks", "n_users_affected", "top_issues", "priority",
]


def quality_overview(evals_df: pd.DataFrame) -> dict:
    """Headline validation numbers for the KPI row."""
    if evals_df.empty:
        return {
            "n_evaluated_spans": 0, "n_checks": 0, "n_failed_checks": 0,
            "n_failed_spans": 0, "span_pass_rate": None, "avg_score": None,
            "n_prompt_issues": 0, "n_output_issues": 0, "sources": [],
            "annotator_kinds": [],
        }
    work = with_pass_flag(evals_df)
    failed = work.loc[~work["passed"]]
    n_spans = int(work["span_id"].nunique())
    n_failed_spans = int(failed["span_id"].nunique())
    scores = pd.to_numeric(work["score"], errors="coerce").dropna()
    return {
        "n_evaluated_spans": n_spans,
        "n_checks": int(len(work)),
        "n_failed_checks": int(len(failed)),
        "n_failed_spans": n_failed_spans,
        "span_pass_rate": float((n_spans - n_failed_spans) / n_spans) if n_spans else None,
        "avg_score": float(scores.mean()) if not scores.empty else None,
        "n_prompt_issues": int((failed["target"] == "prompt").sum()),
        "n_output_issues": int((failed["target"] != "prompt").sum()),
        "sources": sorted(work["source"].dropna().astype(str).unique().tolist()),
        "annotator_kinds": sorted(
            work["annotator_kind"].dropna().astype(str).unique().tolist()
        ),
    }


# ---- helpers -----------------------------------------------------------------


def _mode(series: pd.Series) -> str:
    values = series.dropna().astype(str)
    values = values[values != ""]
    if values.empty:
        return ""
    return str(values.mode().iloc[0])


def _top_labels(series: pd.Series, top_n: int = 3) -> str:
    counts = series.dropna().astype(str).value_counts().head(top_n)
    return ", ".join(f"{label} ({count})" for label, count in counts.items())


def _preview(series: pd.Series) -> str:
    values = series.dropna().astype(str)
    values = values[values != ""]
    if values.empty:
        return ""
    text = values.iloc[0]
    if len(text) > _EXPLANATION_PREVIEW_CHARS:
        return text[: _EXPLANATION_PREVIEW_CHARS - 1] + "…"
    return text


def _none_if_blank(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
