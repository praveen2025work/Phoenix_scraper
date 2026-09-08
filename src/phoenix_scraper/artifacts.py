"""Render (and, on promote, write) the ladder's draft artifacts.

Rung 1: `skills/<name>.md` for a `new_skill` candidate; a paste-ready
`example_prompts` / `keywords` block for a `strengthen_skill` candidate (no file
written — the target is a hand-authored skill). Rung-2 artifacts are Phase D.
Draft files carry `status: draft`; pheonix never edits hand-authored files.
"""

import re
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import Settings
from .models import Candidate, Capability, QueryFilters, SkillEntry, _Frozen
from .skill_coverage import _suggested_keywords, _yaml_block
from .skills import distinctive_words
from .skills_mapper import _NAME_STOPWORDS, _PLACEHOLDER_TOKENS
from .storage import Store
from .taxonomy import suggest_level

_MEMBER_PROMPT_LIMIT = 8


class PromoteResult(_Frozen):
    paths: tuple[str, ...] = ()
    contents: tuple[tuple[str, str], ...] = ()
    wrote_files: bool = False


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return re.sub(r"-{2,}", "-", slug) or "skill"


def dedupe_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    candidate = directory / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def _skill_stem(candidate: Candidate) -> str:
    """The proposal's kebab-case name (mirrors skills_mapper._proposed_name)."""
    words = [
        w
        for w in distinctive_words(candidate.signature or candidate.title)
        if w not in _PLACEHOLDER_TOKENS and w not in _NAME_STOPWORDS
    ]
    return "-".join(words[:4]) or slugify(candidate.title) or f"skill-{candidate.cluster_id}"


def _keywords(candidate: Candidate) -> list[str]:
    name_words = set(distinctive_words(candidate.title))
    words = [
        w
        for w in distinctive_words(candidate.signature or candidate.title)
        if w not in _PLACEHOLDER_TOKENS and w not in name_words
    ]
    return words[:8] or list(distinctive_words(candidate.title))[:6]


def render_new_skill_md(
    candidate: Candidate,
    *,
    capability: Capability,
    member_prompts: list[str],
    today: date,
) -> tuple[str, str]:
    stem = _skill_stem(candidate)
    level, asset_class, _cap = suggest_level(candidate.title)
    ev = candidate.current_evidence
    front: dict = {
        "name": stem,
        "description": f"Answer: {candidate.title.strip()[:120]}",
        "level": level if level != "asset_class" else "capability",
        "capability": capability.id,
        "keywords": _keywords(candidate),
        "example_prompts": member_prompts[:_MEMBER_PROMPT_LIMIT] or [candidate.title],
        "status": "draft",
        "source_candidate": candidate.candidate_id,
        "evidence": {
            "first_seen": candidate.first_seen_at.date().isoformat(),
            "asks": int(ev.get("count", 0)),
            "users": int(ev.get("n_users", 0)),
        },
    }
    if asset_class:
        front["asset_class"] = asset_class
    dumped = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=10**6).rstrip()
    body = (
        f"---\n{dumped}\n---\n\n"
        f"# {stem}\n\n"
        f"<!-- Draft scaffolded by pheonix from candidate {candidate.candidate_id}.\n"
        f"     Fill in the procedure, then set status: active. pheonix stops\n"
        f"     proposing this candidate once a skill matches and demonstrates it. -->\n\n"
        f"## When to use\n"
        f"Recurring across {int(ev.get('n_users', 0))} analysts; "
        f"{int(ev.get('count', 0))} asks since "
        f"{candidate.first_seen_at.date().isoformat()}.\n\n"
        f"## Procedure\n1. TODO\n"
    )
    return f"{stem}.md", body


def render_strengthen_block(
    candidate: Candidate,
    skill: SkillEntry,
    *,
    member_prompts: list[str],
    member_signatures: list[str],
) -> tuple[str, str]:
    keywords = _suggested_keywords(member_signatures, skill)
    block = _yaml_block(skill, member_prompts[:_MEMBER_PROMPT_LIMIT], keywords)
    target = skill.path or f"(skill '{skill.name}' — source file unknown)"
    return target, block


def _member_prompts(store: Store, capability: Capability, candidate: Candidate) -> list[str]:
    f = capability.filter
    frame = store.spans_frame(QueryFilters(
        project=f.project, workflow_stage=f.workflow_stage, asset_class=f.asset_class,
        model_name=f.model_name, search=f.search, limit=5000,
    ))
    if frame.empty or "input_text" not in frame.columns:
        return [candidate.title]
    seen: set[str] = set()
    unique: list[str] = []
    for value in frame["input_text"].tolist():
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            unique.append(text)
    return unique[:_MEMBER_PROMPT_LIMIT] or [candidate.title]


def promote_candidate(
    store: Store,
    capability: Capability,
    candidate: Candidate,
    *,
    now: datetime,
    actor: str,
    settings: Settings,
    dry_run: bool = False,
) -> PromoteResult:
    prompts = _member_prompts(store, capability, candidate)
    cap_dir = Path(settings.capabilities_dir) / capability.id

    if candidate.subtype == "strengthen_skill":
        from .skills import load_all_skills
        skills = {s.name: s for s in load_all_skills(settings)}
        skill = skills.get(candidate.matched_skill or "") or SkillEntry(
            name=candidate.matched_skill or "unknown",
            path=str(cap_dir / "skills" / f"{candidate.matched_skill}.md"),
        )
        target, block = render_strengthen_block(
            candidate, skill, member_prompts=prompts,
            member_signatures=[candidate.signature],
        )
        paths: tuple[str, ...] = (target,)
        contents: tuple[tuple[str, str], ...] = ((target, block),)
        wrote = False
    else:
        skills_dir = cap_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        filename, body = render_new_skill_md(
            candidate, capability=capability, member_prompts=prompts, today=now.date(),
        )
        out_path = dedupe_path(skills_dir, filename[:-3])
        contents = ((str(out_path), body),)
        if not dry_run:
            out_path.write_text(body, encoding="utf-8")
        paths = (str(out_path),)
        wrote = not dry_run

    if not dry_run:
        store.record_candidate_decision_now(
            candidate.candidate_id, "promote", actor, now,
        )
        store.upsert_candidate(candidate.model_copy(update={
            "status": "promoted",
            "promoted_at": now,
            "promoted_artifact_paths": paths,
            "decided_by": actor,
            "decided_at": now,
        }))
    return PromoteResult(paths=paths, contents=contents, wrote_files=wrote)
