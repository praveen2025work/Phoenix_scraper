"""Load the skills catalog (YAML) and scan directories for skill markdown files.

Capability / SKILL.md files may use YAML frontmatter (preferred) or plain
Markdown. Matching fields are taken from frontmatter when present, otherwise
derived from headings, paragraphs, and example lists in the body.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from .config import Settings
from .models import SkillEntry

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_WORD_RE = re.compile(r"[a-z][a-z0-9]+")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.+)$")
_NAME_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EXAMPLE_HEADING_RE = re.compile(
    r"examples?|example\s*prompts?|sample\s*prompts?|prompts?|questions?",
    re.IGNORECASE,
)
_KEYWORD_HEADING_RE = re.compile(r"keywords?", re.IGNORECASE)
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


def slugify_skill_name(text: str) -> str:
    """Turn a heading or label into a kebab-case skill id."""
    slug = _NAME_SLUG_RE.sub("-", text.casefold()).strip("-")
    return slug[:64] if slug else ""


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


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _split_frontmatter(text: str) -> tuple[dict | None, str]:
    """Return (meta_dict_or_None, markdown_body). Invalid YAML → (None, full text)."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None, text
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None, text
    body = text[match.end() :]
    if isinstance(meta, dict):
        return meta, body
    return None, body


def _section_bullets(body: str, heading_re: re.Pattern[str]) -> list[str]:
    """Collect bullet items under headings whose titles match ``heading_re``."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return []
    items: list[str] = []
    for index, match in enumerate(matches):
        title = match.group(2).strip()
        if not heading_re.search(title):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        for line in body[start:end].splitlines():
            bullet = _BULLET_RE.match(line)
            if bullet:
                items.append(bullet.group(1).strip())
    return items


def _first_paragraph(body: str) -> str:
    """First non-heading, non-empty paragraph in the markdown body."""
    chunks: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if chunks:
                break
            continue
        if line.startswith("#"):
            if chunks:
                break
            continue
        if line.startswith("---"):
            continue
        chunks.append(line)
    return " ".join(chunks).strip()


def _question_like_lines(body: str) -> list[str]:
    """Fallback example prompts: question-like lines outside code fences."""
    found: list[str] = []
    in_fence = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith("#"):
            continue
        bullet = _BULLET_RE.match(raw_line)
        text = bullet.group(1).strip() if bullet else line
        if text.lower().startswith("q:"):
            text = text[2:].strip()
        if "?" in text or text.lower().startswith(("why ", "how ", "what ", "when ")):
            found.append(text)
        if len(found) >= 12:
            break
    return found


def _derive_from_markdown(body: str, *, fallback_name: str) -> dict[str, object]:
    h1 = _H1_RE.search(body)
    heading_name = slugify_skill_name(h1.group(1)) if h1 else ""
    name = heading_name or fallback_name
    description = _first_paragraph(body)
    examples = _section_bullets(body, _EXAMPLE_HEADING_RE) or _question_like_lines(body)
    keywords = _section_bullets(body, _KEYWORD_HEADING_RE)
    return {
        "name": name,
        "description": description,
        "example_prompts": examples,
        "keywords": keywords,
    }


def parse_skill_markdown(text: str, *, path: Path | None = None) -> SkillEntry | None:
    """Build a SkillEntry from markdown text (frontmatter and/or MD structure).

    Returns None only when no skill name can be determined.
    """
    text = text.replace("\r\n", "\n")
    if not text.strip():
        return None

    fallback_name = ""
    if path is not None:
        if path.name.casefold() == "skill.md" and path.parent.name:
            fallback_name = slugify_skill_name(path.parent.name)
        else:
            fallback_name = slugify_skill_name(path.stem)

    meta, body = _split_frontmatter(text)
    derived = _derive_from_markdown(body, fallback_name=fallback_name)

    name = ""
    description = ""
    examples: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()

    if meta is not None and meta.get("name"):
        name = str(meta["name"]).strip()
        description = str(meta.get("description", "")).strip()
        examples = _as_str_tuple(
            meta.get("example_prompts") or meta.get("examples") or []
        )
        keywords = _as_str_tuple(meta.get("keywords") or [])
    else:
        name = str(derived["name"] or "").strip()
        description = str(derived["description"] or "").strip()
        examples = _as_str_tuple(derived["example_prompts"])
        keywords = _as_str_tuple(derived["keywords"])

    if not name:
        return None

    # Frontmatter may omit optional fields — fill from Markdown structure.
    if not description:
        description = str(derived["description"] or "").strip()
    if not examples:
        examples = _as_str_tuple(derived["example_prompts"])
    if not keywords:
        keywords = _as_str_tuple(derived["keywords"])
    if not keywords:
        keywords = distinctive_words(
            f"{name.replace('-', ' ')} {description} {' '.join(examples)}"
        )

    return SkillEntry(
        name=name,
        description=description,
        keywords=keywords,
        example_prompts=examples,
        source="skill_md",
        path=str(path) if path is not None else None,
    )


def _parse_skill_md(path: Path) -> SkillEntry | None:
    """Parse one skill markdown file; None if it has no usable name."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None
    entry = parse_skill_markdown(text, path=path)
    if entry is None:
        logger.warning("No usable skill name in %s; skipping", path)
    return entry


def scan_skill_dirs(dirs: list[Path]) -> list[SkillEntry]:
    """Find **/SKILL.md under each directory; unusable files are skipped with a warning."""
    skills: list[SkillEntry] = []
    for directory in dirs:
        if not directory.is_dir():
            logger.warning("Skills directory %s does not exist; skipping", directory)
            continue
        for path in sorted(directory.rglob("SKILL.md")):
            entry = _parse_skill_md(path)
            if entry is not None:
                skills.append(entry)
    return skills


def scan_skill_files(paths: list[Path]) -> list[SkillEntry]:
    """Parse an explicit list of markdown skill files (one skill per file).

    ``scan_skill_dirs`` walks a tree for files named ``SKILL.md``; this reads the
    exact paths given. Used for a capability's loose ``skills/<name>.md`` files
    (see the spec's Rung-1 artifact layout). Missing or unusable files are
    skipped with a warning.
    """
    skills: list[SkillEntry] = []
    for path in paths:
        if not path.is_file():
            continue
        entry = _parse_skill_md(path)
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
