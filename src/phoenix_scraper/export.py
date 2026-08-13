"""Export analysis dataframes to files and render the human-readable report."""

from collections import Counter
from pathlib import Path

import pandas as pd

from .evaluations import PASS_SCORE as _PASS_SCORE
from .models import (
    AnalysisResult,
    PromptCluster,
    SessionRecord,
    SkillGapProposal,
    SkillMatch,
    SpanEvaluation,
)

_SUPPORTED_FORMATS = ("csv", "json", "parquet")

# Spreadsheet formula triggers (OWASP CSV-injection). Span text is end-user
# controlled, and the whole point of these exports is analysts opening them in Excel.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")

_LEVEL_HEADINGS: tuple[tuple[str, str], ...] = (
    ("global", "Global"),
    ("asset_class", "Asset class"),
    ("capability", "Capability"),
)

_TOP_PROMPTS_LIMIT = 20


def sanitize_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with formula triggers in string cells neutralized (leading ')."""

    def _neutralize(value: object) -> object:
        if isinstance(value, str) and value.startswith(_FORMULA_TRIGGERS):
            return "'" + value
        return value

    out = df.copy()
    for col in out.columns:
        # pandas >= 3 uses the dedicated string dtype; object covers mixed columns.
        if pd.api.types.is_string_dtype(out[col]) or out[col].dtype == object:
            out[col] = out[col].map(_neutralize)
    return out


def frame_to_csv_text(df: pd.DataFrame) -> str:
    """Sanitized CSV as a string — used by the API so responses never touch disk."""
    return sanitize_for_csv(df).to_csv(index=False)


def export_frame(df: pd.DataFrame, out_dir: Path, name: str, fmt: str) -> Path:
    """Write ``df`` to ``out_dir/name.fmt``; fmt one of csv|json|parquet."""
    if fmt not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"Unknown export format {fmt!r}; expected one of {', '.join(_SUPPORTED_FORMATS)}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.{fmt}"
    if fmt == "csv":
        sanitize_for_csv(df).to_csv(path, index=False)
    elif fmt == "json":
        df.to_json(path, orient="records", date_format="iso")
    else:
        df.to_parquet(path, index=False)
    return path


def write_markdown_report(
    result: AnalysisResult,
    out_path: Path,
    updates_df: pd.DataFrame | None = None,
) -> Path:
    """Render an AnalysisResult as a markdown report and return the written path.

    ``updates_df`` is the output of skill_coverage.suggested_updates; when given,
    the report carries the concrete edits each skill file needs.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sections = [
        _header(result),
        _top_prompts_section(result.clusters),
        _validation_section(result.evaluations),
        _coverage_section(updates_df),
        _matches_section(result.matches, result.clusters),
        _proposals_section(result.proposals),
        _sessions_section(result.sessions),
    ]
    out_path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    return out_path


# ---- report sections ---------------------------------------------------------


def _header(result: AnalysisResult) -> str:
    generated = result.generated_at.isoformat() if result.generated_at else "n/a"
    return (
        "# Prompt Mining Report\n\n"
        f"- Generated at: {generated}\n"
        f"- Spans analyzed: {result.n_spans_analyzed}\n"
        f"- Prompt clusters: {len(result.clusters)}\n"
        f"- Skill matches: {len(result.matches)}\n"
        f"- Skill gap proposals: {len(result.proposals)}\n"
        f"- Validation checks: {len(result.evaluations)}"
    )


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _top_prompts_section(clusters: tuple[PromptCluster, ...]) -> str:
    title = "## Top prompts"
    if not clusters:
        return f"{title}\n\nNo prompt clusters."
    ranked = sorted(clusters, key=lambda c: c.count, reverse=True)[:_TOP_PROMPTS_LIMIT]
    rows = [
        [
            _escape(c.representative),
            str(c.count),
            str(c.n_sessions),
            str(c.n_users),
            f"${c.total_cost_usd:.2f}",
            ", ".join(c.asset_classes) or "-",
            ", ".join(c.workflow_stages) or "-",
        ]
        for c in ranked
    ]
    table = _md_table(
        ["Prompt", "Count", "Sessions", "Users", "Cost", "Asset classes", "Stages"],
        rows,
    )
    return f"{title}\n\n{table}"


def _validation_section(evaluations: tuple[SpanEvaluation, ...]) -> str:
    """Per-check failure counts, worst first, with one failing example each."""
    title = "## Output & prompt validation"
    if not evaluations:
        return f"{title}\n\nNo validation results."

    applied: Counter[str] = Counter()
    failed: Counter[str] = Counter()
    targets: dict[str, str] = {}
    examples: dict[str, str] = {}
    for evaluation in evaluations:
        applied[evaluation.name] += 1
        targets.setdefault(evaluation.name, evaluation.target)
        if evaluation.score is not None and evaluation.score < _PASS_SCORE:
            failed[evaluation.name] += 1
            examples.setdefault(evaluation.name, evaluation.explanation)

    n_failed = sum(failed.values())
    summary = (
        f"{len(evaluations)} checks over {len({e.span_id for e in evaluations})} spans; "
        f"{n_failed} failed."
    )
    if not n_failed:
        return f"{title}\n\n{summary} Every check passed."

    rows = [
        [
            _escape(name),
            targets.get(name, ""),
            str(count),
            str(applied[name]),
            f"{count / applied[name]:.0%}",
            _escape(examples.get(name, "")),
        ]
        for name, count in failed.most_common()
    ]
    table = _md_table(
        ["Check", "Judges", "Failed", "Evaluated", "Rate", "Example"], rows
    )
    return f"{title}\n\n{summary}\n\n{table}"


def _coverage_section(updates_df: pd.DataFrame | None) -> str:
    """Per skill file, the questions it is asked but does not demonstrate."""
    title = "## Skill coverage gaps — what to add to each file"
    if updates_df is None:
        return f"{title}\n\nNot computed for this report."
    if updates_df.empty:
        return (
            f"{title}\n\nNo gaps: every question routed to a skill is already "
            "demonstrated by that skill's own examples."
        )
    parts = [title, ""]
    for row in updates_df.to_dict("records"):
        evidence = (
            f"{row['uncovered_asks']} asks · {row['n_users']} users · "
            f"{_date_only(row['first_seen'])} to {_date_only(row['last_seen'])}"
        )
        if row["n_new_since_last_run"]:
            evidence += f" · {row['n_new_since_last_run']} new since the last run"
        prompts = "\n".join(f"- {_escape(p)}" for p in row["new_prompts"])
        keywords = ", ".join(row["new_keywords"]) or "-"
        parts.append(
            f"### {_escape(str(row['source_file']))} — {_escape(str(row['skill_name']))}\n\n"
            f"{evidence}\n\n"
            f"Add these `example_prompts`:\n\n{prompts}\n\n"
            f"Add these `keywords`: {keywords}\n"
        )
    return "\n".join(parts)


def _date_only(value: object) -> str:
    text = str(value or "")
    return text[:10] if text else "?"


def _matches_section(
    matches: tuple[SkillMatch, ...], clusters: tuple[PromptCluster, ...]
) -> str:
    title = "## Matched skills"
    if not matches:
        return f"{title}\n\nNo skill matches."
    reps = {c.cluster_id: c.representative for c in clusters}
    rows = [
        [
            _escape(m.skill_name),
            _escape(reps.get(m.cluster_id, m.cluster_id)),
            f"{m.score:.2f}",
            m.method,
        ]
        for m in sorted(matches, key=lambda m: m.score, reverse=True)
    ]
    table = _md_table(["Skill", "Prompt", "Score", "Method"], rows)
    return f"{title}\n\n{table}"


def _proposals_section(proposals: tuple[SkillGapProposal, ...]) -> str:
    title = "## Proposed new skills"
    if not proposals:
        return f"{title}\n\nNo skill gap proposals."
    parts = [title]
    for level, heading in _LEVEL_HEADINGS:
        group = [p for p in proposals if p.level == level]
        if not group:
            continue
        rows = [
            [
                _escape(p.proposed_name),
                p.asset_class or "-",
                p.capability or "-",
                str(p.evidence_count),
                _escape(p.representative_prompt),
                _escape(p.description),
            ]
            for p in sorted(group, key=lambda p: p.evidence_count, reverse=True)
        ]
        table = _md_table(
            ["Proposed skill", "Asset class", "Capability", "Evidence", "Prompt", "Description"],
            rows,
        )
        parts.append(f"### {heading}\n\n{table}")
    return "\n\n".join(parts)


def _sessions_section(sessions: tuple[SessionRecord, ...]) -> str:
    title = "## Session & cost summary"
    if not sessions:
        return f"{title}\n\nNo sessions."
    total_cost = sum(s.total_cost_usd for s in sessions)
    total_tokens = sum(s.total_tokens for s in sessions)
    n_users = len({s.user_id for s in sessions if s.user_id})
    models = sorted({m for s in sessions for m in s.models})
    return (
        f"{title}\n\n"
        f"- Sessions: {len(sessions)}\n"
        f"- Distinct users: {n_users}\n"
        f"- Total tokens: {total_tokens}\n"
        f"- Total cost: ${total_cost:.2f}\n"
        f"- Models: {', '.join(models) or '-'}"
    )
