"""Tests for the skills catalog loader and SKILL.md directory scanner."""

import logging
from pathlib import Path

import pytest

from phoenix_scraper.config import Settings
from phoenix_scraper.models import SkillEntry
from phoenix_scraper.skills import load_all_skills, load_catalog, scan_skill_dirs

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "config" / "skills_catalog.yaml"


def write_skill_md(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestLoadCatalog:
    def test_loads_all_entries(self) -> None:
        skills = load_catalog(CATALOG_PATH)
        assert len(skills) == 9
        assert all(isinstance(s, SkillEntry) for s in skills)

    def test_fields_mapped(self) -> None:
        by_name = {s.name: s for s in load_catalog(CATALOG_PATH)}
        triage = by_name["fx-recon-break-triage"]
        assert triage.level == "asset_class"
        assert triage.asset_class == "fx"
        assert triage.capability == "fobo_recon"
        assert "recon" in triage.keywords
        assert len(triage.example_prompts) == 2
        assert triage.source == "yaml"

    def test_global_entry_has_no_asset_class(self) -> None:
        by_name = {s.name: s for s in load_catalog(CATALOG_PATH)}
        glossary = by_name["glossary-explainer"]
        assert glossary.level == "global"
        assert glossary.asset_class is None

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_catalog(tmp_path / "nope.yaml")

    def test_empty_catalog_returns_empty_list(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.yaml"
        p.write_text("skills: []\n", encoding="utf-8")
        assert load_catalog(p) == []


class TestScanSkillDirs:
    def test_parses_valid_frontmatter(self, tmp_path: Path) -> None:
        path = write_skill_md(
            tmp_path,
            "nested/deep/SKILL.md",
            "---\nname: fx-hedge-helper\n"
            "description: Help hedge FX exposure quickly\n---\n\nBody text.\n",
        )
        skills = scan_skill_dirs([tmp_path])
        assert len(skills) == 1
        entry = skills[0]
        assert entry.name == "fx-hedge-helper"
        assert entry.description == "Help hedge FX exposure quickly"
        assert entry.source == "skill_md"
        assert entry.path == str(path)
        # keywords derived from name + description, without stopwords
        assert "hedge" in entry.keywords
        assert "the" not in entry.keywords

    def test_skips_malformed_files_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        write_skill_md(tmp_path, "good/SKILL.md", "---\nname: good-skill\ndescription: ok\n---\n")
        write_skill_md(tmp_path, "no-frontmatter/SKILL.md", "just some markdown, no frontmatter")
        write_skill_md(tmp_path, "bad-yaml/SKILL.md", "---\nname: [unclosed\n---\n")
        write_skill_md(tmp_path, "no-name/SKILL.md", "---\ndescription: nameless\n---\n")
        with caplog.at_level(logging.WARNING):
            skills = scan_skill_dirs([tmp_path])
        assert [s.name for s in skills] == ["good-skill"]
        assert len(caplog.records) >= 3

    def test_nonexistent_dir_is_tolerated(self, tmp_path: Path) -> None:
        assert scan_skill_dirs([tmp_path / "does-not-exist"]) == []

    def test_empty_dir_list(self) -> None:
        assert scan_skill_dirs([]) == []


class TestLoadAllSkills:
    def test_combines_catalog_and_dirs(self, tmp_path: Path) -> None:
        write_skill_md(
            tmp_path, "extra/SKILL.md", "---\nname: extra-skill\ndescription: something new\n---\n"
        )
        settings = Settings(skills_catalog=CATALOG_PATH, skills_dirs=str(tmp_path))
        skills = load_all_skills(settings)
        names = [s.name for s in skills]
        assert "fx-recon-break-triage" in names
        assert "extra-skill" in names
        assert len(skills) == 10

    def test_dedup_by_name_catalog_wins(self, tmp_path: Path) -> None:
        write_skill_md(
            tmp_path,
            "dup/SKILL.md",
            "---\nname: glossary-explainer\ndescription: duplicate of a catalog skill\n---\n",
        )
        settings = Settings(skills_catalog=CATALOG_PATH, skills_dirs=str(tmp_path))
        skills = load_all_skills(settings)
        dupes = [s for s in skills if s.name == "glossary-explainer"]
        assert len(dupes) == 1
        assert dupes[0].source == "yaml"

    def test_no_dirs_configured(self) -> None:
        settings = Settings(skills_catalog=CATALOG_PATH, skills_dirs="")
        assert len(load_all_skills(settings)) == 9
