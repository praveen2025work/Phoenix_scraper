"""Load the skill set that applies to one capability (local overrides catalog)."""

from __future__ import annotations

from .capability import capability_skill_dirs
from .config import Settings
from .models import Capability, SkillEntry
from .skills import load_all_skills, scan_skill_files


def load_capability_skills(settings: Settings, capability: Capability) -> list[SkillEntry]:
    """This capability's own loose ``skills/*.md`` + catalog + PHEONIX_SKILLS_DIRS,
    de-duped by name.

    The capability's own files come FIRST, so a `skills/<name>.md` **overrides** a
    shared-catalog entry of the same name for this capability only. That is the
    whole point of the per-capability directory: coverage tells you "add this
    example to `fobo-break-triage`", and dropping that file here has to actually
    take effect. Letting the catalog win made the fix a silent no-op.
    """
    cap_skill_files = [
        path
        for directory in capability_skill_dirs(settings.capabilities_dir, capability.id)
        for path in sorted(directory.glob("*.md"))
    ]
    combined = scan_skill_files(cap_skill_files) + load_all_skills(settings)
    seen: set[str] = set()
    unique: list[SkillEntry] = []
    for skill in combined:
        if skill.name not in seen:
            seen.add(skill.name)
            unique.append(skill)
    return unique
