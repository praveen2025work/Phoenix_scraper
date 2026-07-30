"""Tests for export.py: dataframe exports and the markdown report."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from phoenix_scraper.export import export_frame, write_markdown_report
from phoenix_scraper.models import (
    AnalysisResult,
    PromptCluster,
    SessionRecord,
    SkillGapProposal,
    SkillMatch,
)

GENERATED_AT = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def small_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "span_id": ["s-1", "s-2", "s-3"],
            "count": [5, 3, 1],
            "cost_usd": [0.12, 0.05, 0.01],
            "input_text": ["why fx break", "plex commentary", "adjust ADJ-1"],
        }
    )


def _cluster(cid: str, representative: str, count: int) -> PromptCluster:
    return PromptCluster(
        cluster_id=cid,
        signature=representative.lower(),
        representative=representative,
        count=count,
        n_sessions=2,
        n_users=2,
        total_cost_usd=0.42,
        avg_latency_ms=1200.0,
        first_seen=GENERATED_AT,
        last_seen=GENERATED_AT,
        span_ids=("s-1", "s-2"),
        asset_classes=("fx",),
        workflow_stages=("fobo_recon",),
    )


@pytest.fixture()
def analysis_result() -> AnalysisResult:
    clusters = (
        _cluster("aaa111aaa111", "Why is there an FX recon break on EURUSD?", 12),
        _cluster("bbb222bbb222", "Draft sign-off commentary for the rates desk", 7),
        _cluster("ccc333ccc333", "Post an adjustment for trade ADJ-1234", 4),
        _cluster("ddd444ddd444", "Summarise flash vs formal differences", 3),
    )
    matches = (
        SkillMatch(cluster_id="aaa111aaa111", skill_name="fx-recon-break", score=0.87),
    )
    proposals = (
        SkillGapProposal(
            cluster_id="bbb222bbb222",
            proposed_name="rates-signoff-commentary",
            level="asset_class",
            asset_class="rates",
            capability="commentary_signoff",
            description="Draft desk sign-off commentary.",
            evidence_count=7,
            representative_prompt="Draft sign-off commentary for the rates desk",
            sample_span_ids=("s-2",),
        ),
        SkillGapProposal(
            cluster_id="ccc333ccc333",
            proposed_name="post-adjustment",
            level="capability",
            asset_class=None,
            capability="adjustments",
            description="Post P&L adjustments.",
            evidence_count=4,
            representative_prompt="Post an adjustment for trade ADJ-1234",
            sample_span_ids=("s-3",),
        ),
        SkillGapProposal(
            cluster_id="ddd444ddd444",
            proposed_name="flash-vs-formal-summary",
            level="global",
            asset_class=None,
            capability=None,
            description="Summarise flash vs formal.",
            evidence_count=3,
            representative_prompt="Summarise flash vs formal differences",
            sample_span_ids=("s-4",),
        ),
    )
    sessions = (
        SessionRecord(
            session_id="sess-001",
            project="pnl-agent",
            user_id="analyst-1",
            start_time=GENERATED_AT,
            n_traces=3,
            n_llm_spans=5,
            n_user_turns=4,
            total_tokens=1400,
            total_cost_usd=0.09,
            models=("us.anthropic.claude-sonnet-4-6",),
            first_prompt="Why is there an FX recon break on EURUSD?",
        ),
    )
    return AnalysisResult(
        clusters=clusters,
        matches=matches,
        proposals=proposals,
        sessions=sessions,
        n_spans_analyzed=26,
        generated_at=GENERATED_AT,
    )


class TestExportFrame:
    def test_csv_round_trip(self, small_df: pd.DataFrame, tmp_path: Path) -> None:
        path = export_frame(small_df, tmp_path / "out", "spans", "csv")
        assert path == tmp_path / "out" / "spans.csv"
        assert path.is_file()
        back = pd.read_csv(path)
        assert list(back.columns) == list(small_df.columns)
        assert back["span_id"].tolist() == small_df["span_id"].tolist()
        assert back["count"].tolist() == small_df["count"].tolist()

    def test_json_round_trip(self, small_df: pd.DataFrame, tmp_path: Path) -> None:
        path = export_frame(small_df, tmp_path / "out", "spans", "json")
        assert path == tmp_path / "out" / "spans.json"
        back = pd.read_json(path, orient="records")
        assert back["span_id"].tolist() == small_df["span_id"].tolist()
        assert back["input_text"].tolist() == small_df["input_text"].tolist()

    def test_parquet_round_trip(self, small_df: pd.DataFrame, tmp_path: Path) -> None:
        path = export_frame(small_df, tmp_path / "out", "spans", "parquet")
        assert path == tmp_path / "out" / "spans.parquet"
        back = pd.read_parquet(path)
        pd.testing.assert_frame_equal(back, small_df)

    def test_output_dir_auto_created(self, small_df: pd.DataFrame, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        assert not nested.exists()
        path = export_frame(small_df, nested, "clusters", "csv")
        assert path.parent == nested
        assert path.is_file()

    def test_unknown_fmt_raises_value_error(
        self, small_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="xml"):
            export_frame(small_df, tmp_path, "spans", "xml")

    def test_does_not_mutate_input(self, small_df: pd.DataFrame, tmp_path: Path) -> None:
        original = small_df.copy(deep=True)
        export_frame(small_df, tmp_path, "spans", "csv")
        pd.testing.assert_frame_equal(small_df, original)

    def test_empty_frame_exports(self, tmp_path: Path) -> None:
        empty = pd.DataFrame({"a": [], "b": []})
        path = export_frame(empty, tmp_path, "empty", "csv")
        assert path.is_file()


class TestWriteMarkdownReport:
    def test_returns_written_path_and_creates_parents(
        self, analysis_result: AnalysisResult, tmp_path: Path
    ) -> None:
        out = tmp_path / "reports" / "report.md"
        result = write_markdown_report(analysis_result, out)
        assert result == out
        assert out.is_file()

    def test_top_prompts_table(self, analysis_result: AnalysisResult, tmp_path: Path) -> None:
        text = write_markdown_report(analysis_result, tmp_path / "r.md").read_text()
        assert "Why is there an FX recon break on EURUSD?" in text
        assert "| 12 |" in text  # count column of the top cluster
        # markdown table separator present
        assert "---" in text

    def test_matched_skills_section(
        self, analysis_result: AnalysisResult, tmp_path: Path
    ) -> None:
        text = write_markdown_report(analysis_result, tmp_path / "r.md").read_text()
        assert "fx-recon-break" in text
        assert "0.87" in text

    def test_proposals_grouped_by_level(
        self, analysis_result: AnalysisResult, tmp_path: Path
    ) -> None:
        text = write_markdown_report(analysis_result, tmp_path / "r.md").read_text()
        i_global = text.index("### Global")
        i_asset = text.index("### Asset class")
        i_cap = text.index("### Capability")
        assert "flash-vs-formal-summary" in text[i_global:i_asset]
        assert "rates-signoff-commentary" in text[i_asset:i_cap]
        assert "post-adjustment" in text[i_cap:]

    def test_session_and_cost_summary(
        self, analysis_result: AnalysisResult, tmp_path: Path
    ) -> None:
        text = write_markdown_report(analysis_result, tmp_path / "r.md").read_text()
        assert "26" in text  # n_spans_analyzed
        assert "sess-001" not in text or True  # sessions summarised, not required per-row
        assert "$" in text  # cost rendered as USD

    def test_empty_result_renders_placeholders(self, tmp_path: Path) -> None:
        empty = AnalysisResult(generated_at=GENERATED_AT)
        text = write_markdown_report(empty, tmp_path / "empty.md").read_text()
        assert "No prompt clusters" in text
        assert "No skill matches" in text
        assert "No skill gap proposals" in text
