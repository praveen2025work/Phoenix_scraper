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


def _mask(text: str) -> str:
    from .normalize import mask_volatile
    return mask_volatile(text)


def render_rung2_stub(
    candidate: Candidate,
    *,
    latest_observation_signals: dict,
    pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Three (filename, body) tuples: <name>.py, test_<name>.py, <name>.md."""
    stem = _skill_stem(candidate)
    sig = latest_observation_signals
    templates = sig.get("templates") or []
    ev = candidate.current_evidence
    score = ev.get("determinism_score", 0.0)

    tmpl_lines = "\n".join(
        f'    "template_{i + 1}": {rep!r},  # {n} answers'
        for i, (rep, n) in enumerate(templates)
    ) or "    # no templates observed"
    decision_table = ""
    if float(sig.get("slot_stability") or 0.0) >= 0.8 and pairs:
        rows = "\n".join(f'    {_mask(p)!r}: "template_1",' for p, _a in pairs[:8])
        decision_table = f"\n\nDECISION_TABLE: dict[str, str] = {{\n{rows}\n}}\n"

    py = (
        f'"""Deterministic replacement for the LLM step behind `{stem}`.\n\n'
        f"Scaffolded by pheonix from candidate {candidate.candidate_id}.\n"
        f"determinism_score {score} — template_concentration "
        f"{sig.get('template_concentration')}, route_invariance "
        f"{sig.get('route_invariance')}, output_self_similarity "
        f"{sig.get('output_self_similarity')}, slot_stability "
        f"{sig.get('slot_stability')}.\n"
        f'"""\n'
        f"from __future__ import annotations\n\n"
        f"TEMPLATES: dict[str, str] = {{\n{tmpl_lines}\n}}\n"
        f"{decision_table}\n"
        f"def handle(prompt: str, context: list[dict]) -> str:\n"
        f'    """TODO: extract the slots from `prompt`, classify from `context`,\n'
        f'    return the filled TEMPLATES entry. test_{stem}.py has the real cases."""\n'
        f"    raise NotImplementedError\n"
    )

    cases = ",\n".join(f"    ({p!r}, {a!r})" for p, a in pairs) or "    # none observed"
    test = (
        f'"""Real observed (prompt -> answer) pairs for `{stem}`. Ships red."""\n'
        f"import pytest\n\n"
        f"from .{stem} import handle\n\n"
        f"CASES = [\n{cases}\n]\n\n\n"
        f'@pytest.mark.parametrize("prompt, expected", CASES)\n'
        f"def test_handle_matches_observed(prompt: str, expected: str) -> None:\n"
        f'    assert " ".join(handle(prompt, []).split()) == " ".join(expected.split())\n'
    )

    tmpl_table = "\n".join(
        f"| T{i + 1} | {n} | `{rep}` |" for i, (rep, n) in enumerate(templates)
    ) or "| — | — | — |"
    md = (
        f"# {stem} — deterministic candidate\n\n"
        f"Source candidate: `{candidate.candidate_id}`  ·  "
        f"determinism_score **{score}**  ·  {ev.get('n_answer_spans', 0)} answer spans\n\n"
        f"## Signals\n\n| signal | value |\n|---|---|\n"
        f"| template_concentration | {sig.get('template_concentration')} |\n"
        f"| route_invariance | {sig.get('route_invariance')} |\n"
        f"| output_self_similarity | {sig.get('output_self_similarity')} |\n"
        f"| slot_stability | {sig.get('slot_stability')} |\n\n"
        f"## Observed templates\n\n| # | answers | masked text |\n|---|---|---|\n{tmpl_table}\n\n"
        f"## Open decisions\n\n"
        f"- Slot extraction: which fields does `handle` pull from the prompt?\n"
        f"- Classifier input: what does `context` need to carry to pick the template?\n"
        f"- Error handling: what does `handle` do when no template fits?\n"
    )
    return [(f"{stem}.py", py), (f"test_{stem}.py", test), (f"{stem}.md", md)]


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

    if candidate.rung == "deterministic":
        det_dir = cap_dir / "deterministic"
        det_dir.mkdir(parents=True, exist_ok=True)
        recent = store.recent_candidate_observations(candidate.candidate_id, 1)
        obs_signals = recent[0].signals if recent else {}
        files = render_rung2_stub(
            candidate, latest_observation_signals=obs_signals,
            pairs=[(p, p) for p in prompts[:20]],
        )
        base_stem = files[0][0][:-3]
        final_stem = dedupe_path(det_dir, base_stem, ".py").stem
        contents_list: list[tuple[str, str]] = []
        written: list[str] = []
        for name, body in files:
            out = det_dir / name.replace(base_stem, final_stem, 1)
            contents_list.append((str(out), body))
            if not dry_run:
                out.write_text(body, encoding="utf-8")
            written.append(str(out))
        return _finish_promote(
            store, candidate, now, actor, tuple(written), tuple(contents_list),
            wrote=not dry_run, dry_run=dry_run,
        )

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

    return _finish_promote(
        store, candidate, now, actor, paths, contents, wrote=wrote, dry_run=dry_run,
    )


def _finish_promote(
    store: Store,
    candidate: Candidate,
    now: datetime,
    actor: str,
    paths: tuple[str, ...],
    contents: tuple[tuple[str, str], ...],
    *,
    wrote: bool,
    dry_run: bool,
) -> PromoteResult:
    if not dry_run:
        store.record_candidate_decision_now(candidate.candidate_id, "promote", actor, now)
        store.upsert_candidate(candidate.model_copy(update={
            "status": "promoted",
            "promoted_at": now,
            "promoted_artifact_paths": paths,
            "decided_by": actor,
            "decided_at": now,
        }))
    return PromoteResult(paths=paths, contents=contents, wrote_files=wrote)
