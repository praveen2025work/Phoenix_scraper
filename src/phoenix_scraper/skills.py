"""Load the skills catalog (YAML) and scan directories for SKILL.md files."""

import logging
import re
from pathlib import Path

import yaml

from .config import Settings
from .models import SkillEntry

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_WORD_RE = re.compile(r"[a-z][a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "into", "are", "was",
        "were", "has", "have", "had", "not", "but", "all", "any", "can", "will",
        "you", "your", "our", "their", "his", "her", "its", "them", "they", "what",
        "which", "who", "how", "why", "when", "where", "does", "did", "should",
        "would", "could", "about", "above", "below", "between", "against", "each",
        "per", "via", "use", "used", "using", "help", "helps",
    }
)


def distinctive_words(text: str, max_words: int = 12) -> tuple[str, ...]:
    """Lowercased content words (order-preserving, de-duplicated, stopwords removed)."""
    seen: list[str] = []
    for word in _WORD_RE.findall(text.casefold()):
        if len(word) >= 3 and word not in _STOPWORDS and word not in seen:
            seen.append(word)
        if len(seen) >= max_words:
            break
    return tuple(seen)


def load_catalog(path: Path) -> list[SkillEntry]:
    """Parse config/skills_catalog.yaml into SkillEntry objects (source='yaml')."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("skills") or []
    skills: list[SkillEntry] = []
    for item in entries:
        if not isinstance(item, dict) or not item.get("name"):
            logger.warning("Skipping malformed catalog entry in %s: %r", path, item)
            continue
        skills.append(
            SkillEntry(
                name=str(item["name"]),
                level=item.get("level", "global"),
                asset_class=item.get("asset_class"),
                capability=item.get("capability"),
                description=str(item.get("description", "")),
                keywords=tuple(str(k) for k in item.get("keywords", [])),
                example_prompts=tuple(str(p) for p in item.get("example_prompts", [])),
                source="yaml",
                path=str(path),
            )
        )
    return skills


def _parse_skill_md(path: Path) -> SkillEntry | None:
    """Parse one SKILL.md file's YAML frontmatter; None if malformed."""
    match = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        logger.warning("No YAML frontmatter in %s; skipping", path)
        return None
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML frontmatter in %s: %s", path, exc)
        return None
    if not isinstance(meta, dict) or not meta.get("name"):
        logger.warning("Frontmatter missing 'name' in %s; skipping", path)
        return None
    name = str(meta["name"])
    description = str(meta.get("description", ""))
    return SkillEntry(
        name=name,
        description=description,
        keywords=distinctive_words(f"{name.replace('-', ' ')} {description}"),
        source="skill_md",
        path=str(path),
    )


def scan_skill_dirs(dirs: list[Path]) -> list[SkillEntry]:
    """Find **/SKILL.md under each directory; malformed files are skipped with a warning."""
    skills: list[SkillEntry] = []
    for directory in dirs:
        if not directory.is_dir():
            logger.warning("Skills directory %s does not exist; skipping", directory)
            continue
        for path in sorted(directory.rglob("SKILL.md")):
            try:
                entry = _parse_skill_md(path)
            except OSError as exc:
                logger.warning("Could not read %s: %s", path, exc)
                continue
            if entry is not None:
                skills.append(entry)
    return skills


def load_all_skills(settings: Settings) -> list[SkillEntry]:
    """Catalog entries plus scanned SKILL.md entries, de-duplicated by name (catalog wins)."""
    combined = load_catalog(settings.skills_catalog) + scan_skill_dirs(
        settings.skills_dir_paths()
    )
    seen: set[str] = set()
    unique: list[SkillEntry] = []
    for skill in combined:
        if skill.name not in seen:
            seen.add(skill.name)
            unique.append(skill)
    return unique
