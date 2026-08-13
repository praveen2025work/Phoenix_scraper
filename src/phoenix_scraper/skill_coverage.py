"""What each skill file covers, what it misses, and what changed since last run.

`skills_mapper` answers "which skill owns this question". This module answers the
follow-up an owner actually has to act on: **the skill owns it — does the skill
file actually show it?**

A cluster can match a skill on keywords alone while none of that skill's
`example_prompts` demonstrates the phrasing users are really typing. Those
clusters are the file's blind spots: the skill is being selected for questions it
was never written to answer. Coverage is measured per **skill file**, since that
is the artifact someone edits.

Two views, both keyed on the file:

- **coverage** — of the asks routed to this file, how many does it demonstrate?
- **delta** — which of its blind spots are new since the previous analysis run?

and one output: a paste-ready block of `example_prompts` and `keywords` to add.
"""

from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd
import yaml
from rapidfuzz import fuzz

from .models import SkillEntry
from .skills import distinctive_words
from .taxonomy import ASSET_CLASS_KEYWORDS

# Cluster status relative to the previous analysis run.
NEW = "new"
GROWING = "growing"
STABLE = "stable"
SHRINKING = "shrinking"
GONE = "gone"

# A count must move by more than this share to read as growth rather than noise.
_MOVEMENT_TOLERANCE = 0.20
_KEYWORD_SUGGESTION_LIMIT = 8
_EVIDENCE_PROMPT_CHARS = 120


def coverage_score(representative: str, skill: SkillEntry) -> float:
    """0-1 similarity between a real question and what the skill file declares.

    Compared against the skill's own `example_prompts` first and its description
    second — the same reference set `skills_mapper._fuzzy_ratio` scores against,
    so "matched" and "covered" are measured on one scale.
    """
    references = [p for p in (*skill.example_prompts, skill.description) if p]
    if not references or not representative:
        return 0.0
    return max(fuzz.token_set_ratio(representative, ref) for ref in references) / 100.0


def source_file(skill: SkillEntry) -> str:
    """The file an owner would edit — the basename is what people call the skill."""
    if not skill.path:
        return f"{skill.name} (no file)"
    path = Path(skill.path)
    # A SKILL.md is identified by its directory; a shared catalog by its filename.
    if path.name.upper() == "SKILL.MD" and path.parent.name:
        return f"{path.parent.name}/{path.name}"
    return path.name


def annotate_coverage(
    clusters_df: pd.DataFrame,
    matches_df: pd.DataFrame,
    skills: Sequence[SkillEntry],
    threshold: float = 0.70,
) -> pd.DataFrame:
    """One row per matched cluster, marked covered or not by its own skill file."""
    if clusters_df.empty or matches_df.empty:
        return pd.DataFrame(columns=_ANNOTATED_COLUMNS)
    by_name = {s.name: s for s in skills}
    # matches_frame() already carries representative/count; drop them so the
    # merge cannot produce _x/_y suffixes the callers below would miss.
    matches = matches_df.loc[:, ["cluster_id", "skill_name", "score"]]
    joined = matches.merge(clusters_df, on="cluster_id", how="inner")
    if joined.empty:
        return pd.DataFrame(columns=_ANNOTATED_COLUMNS)

    rows = []
    for record in joined.to_dict("records"):
        skill = by_name.get(record["skill_name"])
        if skill is None:
            continue
        representative = str(record.get("representative") or "")
        score = coverage_score(representative, skill)
        rows.append(
            {
                "skill_name": skill.name,
                "source_file": source_file(skill),
                "skill_source": skill.source,
                "cluster_id": record["cluster_id"],
                "representative": representative,
                "signature": str(record.get("signature") or representative),
                "count": int(record.get("count") or 0),
                "n_users": int(record.get("n_users") or 0),
                "first_seen": record.get("first_seen"),
                "last_seen": record.get("last_seen"),
                "match_score": float(record.get("score") or 0.0),
                "coverage_score": score,
                "covered": bool(score >= threshold),
                "n_declared_examples": len(skill.example_prompts),
            }
        )
    return pd.DataFrame(rows, columns=_ANNOTATED_COLUMNS)


_ANNOTATED_COLUMNS = [
    "skill_name", "source_file", "skill_source", "cluster_id", "representative",
    "signature", "count", "n_users", "first_seen", "last_seen", "match_score",
    "coverage_score", "covered", "n_declared_examples",
]


def skill_coverage(annotated_df: pd.DataFrame) -> pd.DataFrame:
    """Per skill file: how much of what it is asked does it actually demonstrate?

    ``coverage`` is by ASKS, not by cluster — a blind spot asked 40 times matters
    more than one asked twice, and a cluster-count average would hide that.
    """
    if annotated_df.empty:
        return pd.DataFrame(columns=_COVERAGE_COLUMNS)
    rows = []
    for (skill_name, file_name), group in annotated_df.groupby(
        ["skill_name", "source_file"], sort=False
    ):
        covered = group.loc[group["covered"]]
        uncovered = group.loc[~group["covered"]]
        n_asks = int(group["count"].sum())
        covered_asks = int(covered["count"].sum())
        rows.append(
            {
                "skill_name": str(skill_name),
                "source_file": str(file_name),
                "n_declared_examples": int(group["n_declared_examples"].max()),
                "n_clusters": int(len(group)),
                "n_asks": n_asks,
                "n_covered_asks": covered_asks,
                "n_uncovered_asks": n_asks - covered_asks,
                "n_uncovered_clusters": int(len(uncovered)),
                "coverage": float(covered_asks / n_asks) if n_asks else 0.0,
                "n_users_uncovered": int(uncovered["n_users"].max())
                if not uncovered.empty
                else 0,
                "top_gap": str(uncovered.sort_values("count", ascending=False)
                               .iloc[0]["representative"]) if not uncovered.empty else "",
            }
        )
    df = pd.DataFrame(rows, columns=_COVERAGE_COLUMNS)
    return df.sort_values(
        ["n_uncovered_asks", "n_asks"], ascending=False
    ).reset_index(drop=True)


_COVERAGE_COLUMNS = [
    "skill_name", "source_file", "n_declared_examples", "n_clusters", "n_asks",
    "n_covered_asks", "n_uncovered_asks", "n_uncovered_clusters", "coverage",
    "n_users_uncovered", "top_gap",
]


def uncovered_queries(
    annotated_df: pd.DataFrame, deltas_df: pd.DataFrame | None = None
) -> pd.DataFrame:
    """The blind spots themselves: real questions the skill file does not show.

    When ``deltas_df`` is supplied each row carries its status against the
    previous run, so "new since last week" is visible next to "asked all along".
    """
    if annotated_df.empty:
        return pd.DataFrame(columns=_UNCOVERED_COLUMNS)
    gaps = annotated_df.loc[~annotated_df["covered"]].copy()
    if gaps.empty:
        return pd.DataFrame(columns=_UNCOVERED_COLUMNS)
    gaps["status"] = _status_for(gaps["cluster_id"], deltas_df)
    gaps["count_change"] = _change_for(gaps["cluster_id"], deltas_df)
    return (
        gaps.loc[:, _UNCOVERED_COLUMNS]
        .sort_values(["count", "n_users"], ascending=False)
        .reset_index(drop=True)
    )


_UNCOVERED_COLUMNS = [
    "skill_name", "source_file", "cluster_id", "representative", "signature", "count",
    "n_users", "first_seen", "last_seen", "match_score", "coverage_score",
    "status", "count_change",
]


def cluster_deltas(
    current_df: pd.DataFrame, previous_df: pd.DataFrame
) -> pd.DataFrame:
    """What changed between two analysis runs, per prompt cluster.

    cluster_id is sha1(signature), so it is stable across runs for the same
    normalized question — the join key needs no fuzzy matching.

    An EMPTY ``previous_df`` means there is no earlier run to compare against,
    which is not the same as an earlier run that saw nothing: calling every
    cluster "new since the last run" on a first run would be a lie. Callers get
    an empty frame, and every status downstream stays blank.
    """
    if previous_df.empty or current_df.empty:
        return pd.DataFrame(columns=_DELTA_COLUMNS)
    current = _counts_by_cluster(current_df)
    previous = _counts_by_cluster(previous_df)
    merged = current.merge(
        previous, on="cluster_id", how="outer", suffixes=("", "_prev")
    )
    merged["count"] = merged["count"].fillna(0).astype(int)
    merged["count_prev"] = merged["count_prev"].fillna(0).astype(int)
    merged["representative"] = merged["representative"].fillna(
        merged["representative_prev"]
    ).fillna("")
    merged["skill_name"] = merged["skill_name"].fillna(merged["skill_name_prev"])
    merged["count_change"] = merged["count"] - merged["count_prev"]
    merged["status"] = [
        _classify(row["count"], row["count_prev"])
        for row in merged.to_dict("records")
    ]
    return (
        merged.loc[:, _DELTA_COLUMNS]
        .sort_values(["count_change", "count"], ascending=False)
        .reset_index(drop=True)
    )


_DELTA_COLUMNS = [
    "cluster_id", "representative", "skill_name", "count", "count_prev",
    "count_change", "status",
]


def suggested_updates(
    uncovered_df: pd.DataFrame,
    skills: Sequence[SkillEntry],
    max_prompts: int = 8,
) -> pd.DataFrame:
    """Per skill file, the exact `example_prompts` and `keywords` to add.

    Prompts are the highest-volume blind spots (they carry the most evidence);
    keywords are the distinctive words those questions use that the skill does
    not already list, which is what makes the matcher find them next time.
    """
    if uncovered_df.empty:
        return pd.DataFrame(columns=_UPDATE_COLUMNS)
    by_name = {s.name: s for s in skills}
    rows = []
    for skill_name, group in uncovered_df.groupby("skill_name", sort=False):
        skill = by_name.get(str(skill_name))
        if skill is None:
            continue
        ranked = group.sort_values("count", ascending=False)
        prompts = [
            str(p) for p in ranked["representative"].head(max_prompts) if str(p).strip()
        ]
        if not prompts:
            continue
        signatures = [str(v) for v in ranked["signature"].head(max_prompts)]
        keywords = _suggested_keywords(signatures, skill)
        rows.append(
            {
                "skill_name": str(skill_name),
                "source_file": str(ranked.iloc[0]["source_file"]),
                "n_new_prompts": len(prompts),
                "n_new_keywords": len(keywords),
                "uncovered_asks": int(ranked["count"].sum()),
                "n_users": int(ranked["n_users"].max()),
                "first_seen": ranked["first_seen"].min(),
                "last_seen": ranked["last_seen"].max(),
                "n_new_since_last_run": int((ranked["status"] == NEW).sum()),
                "new_prompts": prompts,
                "new_keywords": keywords,
                "yaml_block": _yaml_block(skill, prompts, keywords),
            }
        )
    df = pd.DataFrame(rows, columns=_UPDATE_COLUMNS)
    if df.empty:
        return df
    return df.sort_values("uncovered_asks", ascending=False).reset_index(drop=True)


_UPDATE_COLUMNS = [
    "skill_name", "source_file", "n_new_prompts", "n_new_keywords",
    "uncovered_asks", "n_users", "first_seen", "last_seen",
    "n_new_since_last_run", "new_prompts", "new_keywords", "yaml_block",
]


def updates_markdown(updates_df: pd.DataFrame) -> str:
    """The whole set of suggested edits as one paste-ready markdown document."""
    if updates_df.empty:
        return (
            "# Skill updates\n\nNo gaps: every question routed to a skill is "
            "already demonstrated by that skill's own examples.\n"
        )
    parts = [
        "# Skill updates\n",
        "Questions users actually asked that the matched skill file does not "
        "demonstrate. Paste each block into the named file's frontmatter.\n",
    ]
    for row in updates_df.to_dict("records"):
        evidence = (
            f"{row['uncovered_asks']} asks across {row['n_users']} users, "
            f"{_date(row['first_seen'])} to {_date(row['last_seen'])}"
        )
        if row["n_new_since_last_run"]:
            evidence += f" ({row['n_new_since_last_run']} new since the last run)"
        parts.append(
            f"## {row['source_file']} — {row['skill_name']}\n\n"
            f"{row['yaml_block']}\n"
            f"Evidence: {evidence}\n"
        )
    return "\n".join(parts)


# ---- helpers -----------------------------------------------------------------


def _counts_by_cluster(snapshot_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["cluster_id", "representative", "count", "skill_name"]
    if snapshot_df.empty:
        return pd.DataFrame(columns=columns)
    present = [c for c in columns if c in snapshot_df.columns]
    out = snapshot_df.loc[:, present].copy()
    for missing in set(columns) - set(present):
        out[missing] = None
    return out.loc[:, columns].drop_duplicates("cluster_id")


def _classify(count: int, previous: int) -> str:
    if previous == 0:
        return NEW if count > 0 else GONE
    if count == 0:
        return GONE
    change = (count - previous) / previous
    if change > _MOVEMENT_TOLERANCE:
        return GROWING
    if change < -_MOVEMENT_TOLERANCE:
        return SHRINKING
    return STABLE


def _status_for(
    cluster_ids: pd.Series, deltas_df: pd.DataFrame | None
) -> list[str]:
    if deltas_df is None or deltas_df.empty:
        return [""] * len(cluster_ids)
    lookup = dict(zip(deltas_df["cluster_id"], deltas_df["status"], strict=False))
    return [lookup.get(cid, "") for cid in cluster_ids]


def _change_for(
    cluster_ids: pd.Series, deltas_df: pd.DataFrame | None
) -> list[int]:
    if deltas_df is None or deltas_df.empty:
        return [0] * len(cluster_ids)
    lookup = dict(zip(deltas_df["cluster_id"], deltas_df["count_change"], strict=False))
    return [int(lookup.get(cid, 0)) for cid in cluster_ids]


# Placeholders left by prompt normalization, plus words too generic to route on.
# A keyword the matcher cannot discriminate with is worse than none: it widens
# every future match without making any of them more certain.
_KEYWORD_NOISE = frozenset({
    "num", "date", "ccy", "book", "desk", "id",  # masked placeholders
    "there", "still", "left", "much", "many", "any", "some", "over", "under",
    "give", "show", "tell", "write", "make", "need", "want", "look", "find",
    "off", "out", "one", "two", "new", "old", "day", "days", "today",
    "number", "numbers", "move", "moved", "drove", "close", "closed",
}) | frozenset(ASSET_CLASS_KEYWORDS)  # the desk a question happened to be about
# ... plus the plural/adjectival forms of those desk names.
_KEYWORD_NOISE = _KEYWORD_NOISE | {"equity", "commodity", "foreign", "exchange"}


def _redundant(word: str, existing: set[str]) -> bool:
    """True when the skill already lists this word, or its singular/plural twin.

    Suggesting "breaks" to a skill that already keys on "break" adds a line to
    the file and nothing to the matcher.
    """
    if word in existing:
        return True
    variants = {word.rstrip("s"), f"{word}s", f"{word}es"}
    return bool(variants & existing)


def _suggested_keywords(
    signatures: Iterable[str], skill: SkillEntry
) -> list[str]:
    """Distinctive words in the blind spots that the skill does not already list.

    Extracted from the normalized SIGNATURE, not the raw question, so masked
    volatile tokens (<desk>, <num>, <book>, <date>) never become keywords —
    "credit" and "rates" are the instance a user happened to ask about, not
    something the skill should match on.
    """
    # Anything already in the name, description or keywords is redundant: those
    # are exactly what the matcher scores against today.
    existing = {k.casefold() for k in skill.keywords}
    existing |= set(distinctive_words(f"{skill.name.replace('-', ' ')} "
                                      f"{skill.description}", max_words=40))
    out: list[str] = []
    for signature in signatures:
        for word in distinctive_words(signature, max_words=20):
            if word in _KEYWORD_NOISE or _redundant(word, existing | set(out)):
                continue
            out.append(word)
            if len(out) >= _KEYWORD_SUGGESTION_LIMIT:
                return out
    return out


def _yaml_block(skill: SkillEntry, prompts: list[str], keywords: list[str]) -> str:
    """The block to paste, emitted by the YAML dumper rather than by hand.

    Real prompts contain backslashes (paths), newlines (pasted dumps), colons and
    quotes. Hand-rolled quoting turns those into a block that does not parse —
    and the entire value of this output is that it can be pasted straight into a
    skill file. yaml.safe_dump escapes them correctly and only quotes when it has
    to, so the common case still reads cleanly.
    """
    existing = len(skill.example_prompts)
    kept = (
        f"  # keep the existing {existing}, add:"
        if existing
        else "  # the file declares none today, add:"
    )
    dumped = yaml.safe_dump(
        prompts,
        default_flow_style=False,
        allow_unicode=True,
        width=10**6,  # never wrap: a folded prompt is harder to read and to diff
    ).rstrip()
    lines = ["```yaml", "example_prompts:", kept]
    lines.extend(f"  {line}" for line in dumped.splitlines())
    if keywords:
        lines.append("keywords:")
        lines.append(f"  # add: {', '.join(keywords)}")
    lines.append("```")
    return "\n".join(lines)


def _date(value: object) -> str:
    text = str(value or "")
    return text[:10] if text else "?"
