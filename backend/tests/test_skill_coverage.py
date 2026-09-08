"""Tests for skill coverage, run-over-run deltas, and the suggested updates."""

from pathlib import Path

import pandas as pd
import pytest

from phoenix_scraper import skill_coverage as sc
from phoenix_scraper.models import SkillEntry


def skill(name: str, **overrides) -> SkillEntry:
    defaults = dict(
        name=name,
        description="Triage FOBO reconciliation breaks across asset classes.",
        keywords=("fobo", "break", "recon"),
        example_prompts=("Why is there a FOBO break on the book?",),
        source="yaml",
        path="config/skills_catalog.yaml",
    )
    defaults.update(overrides)
    return SkillEntry(**defaults)


def clusters(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["cluster_id", "signature", "representative", "count", "n_users",
                 "first_seen", "last_seen"],
    )


def cluster(cid: str, representative: str, count: int = 5, **overrides) -> dict:
    row = {
        "cluster_id": cid,
        "signature": representative.casefold(),
        "representative": representative,
        "count": count,
        "n_users": 3,
        "first_seen": "2026-08-01T00:00:00+00:00",
        "last_seen": "2026-08-10T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def matches(pairs: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"cluster_id": c, "skill_name": s, "score": v} for c, s, v in pairs]
    )


class TestSourceFile:
    def test_skill_md_is_named_by_its_directory(self) -> None:
        entry = skill("x", source="skill_md", path="/skills/fobo-triage/SKILL.md")
        assert sc.source_file(entry) == "fobo-triage/SKILL.md"

    def test_catalog_is_named_by_its_filename(self) -> None:
        assert sc.source_file(skill("x")) == "skills_catalog.yaml"

    def test_pathless_skill_is_still_identifiable(self) -> None:
        assert "no file" in sc.source_file(skill("x", path=None))

    def test_windows_style_path(self) -> None:
        entry = skill("x", source="skill_md", path=str(Path("a") / "b" / "SKILL.md"))
        assert sc.source_file(entry).endswith("SKILL.md")


class TestCoverageScore:
    def test_question_matching_an_example_is_covered(self) -> None:
        assert sc.coverage_score("Why is there a FOBO break on the book?", skill("s")) > 0.9

    def test_unrelated_question_scores_low(self) -> None:
        assert sc.coverage_score("Order lunch for the close team", skill("s")) < 0.5

    def test_skill_with_nothing_declared_covers_nothing(self) -> None:
        bare = skill("s", example_prompts=(), description="")
        assert sc.coverage_score("anything at all", bare) == 0.0

    def test_empty_question(self) -> None:
        assert sc.coverage_score("", skill("s")) == 0.0


class TestAnnotateCoverage:
    def test_marks_covered_and_uncovered(self) -> None:
        df = sc.annotate_coverage(
            clusters([
                cluster("c1", "Why is there a FOBO break on the book?"),
                cluster("c2", "Are there recon items still unmatched on the ledger?"),
            ]),
            matches([("c1", "s", 0.8), ("c2", "s", 0.6)]),
            [skill("s")],
            threshold=0.70,
        )
        assert set(df["cluster_id"]) == {"c1", "c2"}
        assert bool(df[df["cluster_id"] == "c1"].iloc[0]["covered"])
        assert not bool(df[df["cluster_id"] == "c2"].iloc[0]["covered"])

    def test_a_cluster_can_match_on_keywords_yet_be_uncovered(self) -> None:
        # The whole premise: the skill owns the question, its examples don't show it.
        df = sc.annotate_coverage(
            clusters([cluster("c1", "Which recon breaks are stuck past T+2 on gilts?")]),
            matches([("c1", "s", 0.62)]),
            [skill("s")],
            threshold=0.70,
        )
        row = df.iloc[0]
        assert row["match_score"] >= 0.55  # matched
        assert not row["covered"]  # but not demonstrated

    def test_match_to_an_unknown_skill_is_dropped(self) -> None:
        df = sc.annotate_coverage(
            clusters([cluster("c1", "anything")]),
            matches([("c1", "ghost-skill", 0.9)]),
            [skill("s")],
        )
        assert df.empty

    def test_carries_the_signature_for_keyword_extraction(self) -> None:
        df = sc.annotate_coverage(
            clusters([cluster("c1", "Recon break on the <book>")]),
            matches([("c1", "s", 0.6)]),
            [skill("s")],
        )
        assert "signature" in df.columns
        assert df.iloc[0]["signature"]

    @pytest.mark.parametrize(
        "cl, mt",
        [
            (clusters([]), matches([("c1", "s", 0.9)])),
            (clusters([cluster("c1", "x")]), pd.DataFrame()),
        ],
    )
    def test_empty_inputs(self, cl: pd.DataFrame, mt: pd.DataFrame) -> None:
        assert sc.annotate_coverage(cl, mt, [skill("s")]).empty


class TestSkillCoverage:
    def test_coverage_is_weighted_by_asks_not_clusters(self) -> None:
        # 1 covered cluster of 90 asks + 1 uncovered of 10 => 90%, not 50%.
        annotated = sc.annotate_coverage(
            clusters([
                cluster("c1", "Why is there a FOBO break on the book?", count=90),
                cluster("c2", "Order lunch for the close team", count=10),
            ]),
            matches([("c1", "s", 0.9), ("c2", "s", 0.6)]),
            [skill("s")],
        )
        row = sc.skill_coverage(annotated).iloc[0]
        assert row["n_asks"] == 100
        assert row["n_covered_asks"] == 90
        assert row["n_uncovered_asks"] == 10
        assert row["coverage"] == pytest.approx(0.9)

    def test_reports_the_biggest_gap(self) -> None:
        annotated = sc.annotate_coverage(
            clusters([
                cluster("c1", "Order lunch for the close team", count=4),
                cluster("c2", "Book a taxi to the airport", count=40),
            ]),
            matches([("c1", "s", 0.6), ("c2", "s", 0.6)]),
            [skill("s")],
        )
        assert sc.skill_coverage(annotated).iloc[0]["top_gap"] == "Book a taxi to the airport"

    def test_worst_covered_skill_ranks_first(self) -> None:
        annotated = sc.annotate_coverage(
            clusters([
                cluster("c1", "Order lunch for the close team", count=50),
                cluster("c2", "Why is there a FOBO break on the book?", count=50),
            ]),
            matches([("c1", "a", 0.6), ("c2", "b", 0.9)]),
            [skill("a"), skill("b")],
        )
        assert sc.skill_coverage(annotated).iloc[0]["skill_name"] == "a"

    def test_fully_covered_skill_has_no_gap(self) -> None:
        annotated = sc.annotate_coverage(
            clusters([cluster("c1", "Why is there a FOBO break on the book?")]),
            matches([("c1", "s", 0.9)]),
            [skill("s")],
        )
        row = sc.skill_coverage(annotated).iloc[0]
        assert row["n_uncovered_asks"] == 0
        assert row["coverage"] == 1.0
        assert row["top_gap"] == ""

    def test_empty(self) -> None:
        assert sc.skill_coverage(pd.DataFrame()).empty


class TestClusterDeltas:
    def _snapshot(self, rows: list[tuple[str, str, int]]) -> pd.DataFrame:
        return pd.DataFrame(
            [{"cluster_id": c, "representative": r, "count": n, "skill_name": "s"}
             for c, r, n in rows]
        )

    def test_classifies_every_movement(self) -> None:
        current = self._snapshot([("a", "A", 10), ("b", "B", 5), ("c", "C", 20)])
        previous = self._snapshot([("b", "B", 5), ("c", "C", 4), ("d", "D", 7)])
        df = sc.cluster_deltas(current, previous).set_index("cluster_id")

        assert df.loc["a", "status"] == sc.NEW
        assert df.loc["b", "status"] == sc.STABLE
        assert df.loc["c", "status"] == sc.GROWING
        assert df.loc["d", "status"] == sc.GONE
        assert df.loc["c", "count_change"] == 16
        assert df.loc["d", "count"] == 0

    def test_small_movement_is_not_growth(self) -> None:
        df = sc.cluster_deltas(
            self._snapshot([("a", "A", 11)]), self._snapshot([("a", "A", 10)])
        )
        assert df.iloc[0]["status"] == sc.STABLE

    def test_shrinking(self) -> None:
        df = sc.cluster_deltas(
            self._snapshot([("a", "A", 2)]), self._snapshot([("a", "A", 10)])
        )
        assert df.iloc[0]["status"] == sc.SHRINKING

    def test_no_previous_run_yields_no_deltas(self) -> None:
        # A first run has nothing to compare against; calling everything "new
        # since the last run" would be a lie.
        assert sc.cluster_deltas(
            self._snapshot([("a", "A", 10)]), pd.DataFrame()
        ).empty

    def test_both_empty(self) -> None:
        assert sc.cluster_deltas(pd.DataFrame(), pd.DataFrame()).empty


class TestUncoveredQueries:
    def _annotated(self) -> pd.DataFrame:
        return sc.annotate_coverage(
            clusters([
                cluster("c1", "Order lunch for the close team", count=9),
                cluster("c2", "Why is there a FOBO break on the book?", count=40),
            ]),
            matches([("c1", "s", 0.6), ("c2", "s", 0.9)]),
            [skill("s")],
        )

    def test_returns_only_the_gaps(self) -> None:
        df = sc.uncovered_queries(self._annotated())
        assert list(df["cluster_id"]) == ["c1"]

    def test_status_blank_without_deltas(self) -> None:
        assert sc.uncovered_queries(self._annotated()).iloc[0]["status"] == ""

    def test_status_attached_from_deltas(self) -> None:
        deltas = pd.DataFrame([
            {"cluster_id": "c1", "status": sc.NEW, "count_change": 9}
        ])
        row = sc.uncovered_queries(self._annotated(), deltas).iloc[0]
        assert row["status"] == sc.NEW
        assert row["count_change"] == 9

    def test_fully_covered_skill_yields_nothing(self) -> None:
        annotated = sc.annotate_coverage(
            clusters([cluster("c1", "Why is there a FOBO break on the book?")]),
            matches([("c1", "s", 0.9)]),
            [skill("s")],
        )
        assert sc.uncovered_queries(annotated).empty

    def test_empty(self) -> None:
        assert sc.uncovered_queries(pd.DataFrame()).empty


class TestSuggestedUpdates:
    def _uncovered(self, count: int = 9) -> pd.DataFrame:
        annotated = sc.annotate_coverage(
            clusters([
                cluster("c1", "Which tickets sit unconfirmed past settlement?",
                        count=count),
            ]),
            matches([("c1", "s", 0.6)]),
            [skill("s")],
        )
        return sc.uncovered_queries(annotated)

    def test_produces_a_paste_ready_block(self) -> None:
        df = sc.suggested_updates(self._uncovered(), [skill("s")])
        row = df.iloc[0]
        assert row["skill_name"] == "s"
        assert row["source_file"] == "skills_catalog.yaml"
        assert row["new_prompts"] == [
            "Which tickets sit unconfirmed past settlement?"
        ]
        assert "example_prompts:" in row["yaml_block"]
        assert "```yaml" in row["yaml_block"]
        assert "Which tickets sit unconfirmed past settlement?" in row["yaml_block"]
        assert row["uncovered_asks"] == 9

    def test_block_notes_how_many_examples_already_exist(self) -> None:
        df = sc.suggested_updates(self._uncovered(), [skill("s")])
        assert "keep the existing 1" in df.iloc[0]["yaml_block"]

    def test_block_says_so_when_the_file_declares_none(self) -> None:
        bare = skill("s", example_prompts=())
        annotated = sc.annotate_coverage(
            clusters([cluster("c1", "Order lunch for the close team")]),
            matches([("c1", "s", 0.6)]),
            [bare],
        )
        df = sc.suggested_updates(sc.uncovered_queries(annotated), [bare])
        assert "declares none today" in df.iloc[0]["yaml_block"]

    def test_prompts_are_capped_and_ranked_by_volume(self) -> None:
        annotated = sc.annotate_coverage(
            clusters([
                cluster(f"c{i}", f"Unrelated question number {i} about taxis", count=i)
                for i in range(1, 8)
            ]),
            matches([(f"c{i}", "s", 0.6) for i in range(1, 8)]),
            [skill("s")],
        )
        df = sc.suggested_updates(
            sc.uncovered_queries(annotated), [skill("s")], max_prompts=3
        )
        prompts = df.iloc[0]["new_prompts"]
        assert len(prompts) == 3
        assert "number 7" in prompts[0]  # highest count first

    @pytest.mark.parametrize(
        "prompt",
        [
            'Why is the "flash" number wrong on taxis?',
            r"Open C:\Users\ops\report and \n the log",  # backslashes are YAML escapes
            "line one\nline two",  # a literal newline would end the scalar
            "  padded with spaces  ",
            "key: value that looks like yaml",
            "- already a list item",
            "*anchor &alias #hash @at",
            "emoji 📊 ünïcode",
        ],
    )
    def test_yaml_block_is_valid_and_lossless(self, prompt: str) -> None:
        # The entire value of this output is that it pastes into a skill file,
        # so it must parse and the prompt must survive byte-for-byte.
        import yaml

        annotated = sc.annotate_coverage(
            clusters([cluster("c1", prompt)]),
            matches([("c1", "s", 0.6)]),
            [skill("s")],
        )
        block = sc.suggested_updates(
            sc.uncovered_queries(annotated), [skill("s")]
        ).iloc[0]["yaml_block"]
        body = "\n".join(
            line for line in block.splitlines() if not line.startswith("```")
        )
        body = "\n".join(
            line for line in body.splitlines() if not line.strip().startswith("keywords:")
        )
        parsed = yaml.safe_load(body)
        assert parsed["example_prompts"] == [prompt]

    def test_counts_gaps_that_are_new_since_the_last_run(self) -> None:
        uncovered = self._uncovered()
        deltas = pd.DataFrame([
            {"cluster_id": "c1", "status": sc.NEW, "count_change": 9}
        ])
        annotated = sc.annotate_coverage(
            clusters([cluster("c1", "Which tickets sit unconfirmed past settlement?")]),
            matches([("c1", "s", 0.6)]),
            [skill("s")],
        )
        df = sc.suggested_updates(
            sc.uncovered_queries(annotated, deltas), [skill("s")]
        )
        assert df.iloc[0]["n_new_since_last_run"] == 1
        assert not uncovered.empty

    def test_unknown_skill_is_skipped(self) -> None:
        assert sc.suggested_updates(self._uncovered(), []).empty

    def test_empty(self) -> None:
        assert sc.suggested_updates(pd.DataFrame(), [skill("s")]).empty


class TestSuggestedKeywords:
    def test_skips_words_the_skill_already_lists(self) -> None:
        result = sc._suggested_keywords(["recon break on the ledger"], skill("s"))
        assert "recon" not in result
        assert "break" not in result
        assert "ledger" in result

    def test_skips_the_plural_of_an_existing_keyword(self) -> None:
        # "breaks" next to an existing "break" adds a line and no matching power.
        assert "breaks" not in sc._suggested_keywords(["recon breaks pending"], skill("s"))

    def test_skips_words_already_in_the_description(self) -> None:
        entry = skill("s", keywords=(), description="Triage reconciliation breaks")
        assert "reconciliation" not in sc._suggested_keywords(
            ["reconciliation of the custodian feed"], entry
        )

    def test_skips_asset_class_names(self) -> None:
        # The desk a question happened to mention is the instance, not the topic.
        result = sc._suggested_keywords(
            ["credit and rates and equities settlement backlog"], skill("s")
        )
        assert "credit" not in result
        assert "rates" not in result
        assert "settlement" in result

    def test_skips_masked_placeholders(self) -> None:
        assert not set(
            sc._suggested_keywords(["<num> <date> <book> <desk>"], skill("s"))
        ) & {"num", "date", "book", "desk"}

    def test_is_capped(self) -> None:
        long_prompt = " ".join(f"distinctword{i}" for i in range(40))
        assert len(sc._suggested_keywords([long_prompt], skill("s"))) <= 8


class TestUpdatesMarkdown:
    def test_renders_each_skill_with_evidence(self) -> None:
        annotated = sc.annotate_coverage(
            clusters([cluster("c1", "Order lunch for the close team", count=12)]),
            matches([("c1", "s", 0.6)]),
            [skill("s")],
        )
        text = sc.updates_markdown(
            sc.suggested_updates(sc.uncovered_queries(annotated), [skill("s")])
        )
        assert "# Skill updates" in text
        assert "skills_catalog.yaml" in text
        assert "Order lunch for the close team" in text
        assert "12 asks" in text

    def test_says_so_when_there_are_no_gaps(self) -> None:
        text = sc.updates_markdown(pd.DataFrame())
        assert "No gaps" in text
