"""Tests for skill vs deterministic prompt-shape classification."""

import json

import pandas as pd

from phoenix_scraper.normalize import clean_user_text
from phoenix_scraper.prompt_shape import (
    display_title,
    expand_cluster_trace_members,
    extract_user_prompt,
    filter_deterministic_source_spans,
    filter_user_ask_spans,
    is_deterministic_shaped,
    is_deterministic_source_span,
    is_skill_shaped,
    is_user_ask_span,
)


class TestCleanUserText:
    def test_removes_literal_backslash_n(self) -> None:
        assert (
            clean_user_text(r"analyze UAXK\nand UZRZ journals\n")
            == "analyze UAXK and UZRZ journals"
        )

    def test_collapses_real_newlines_and_tabs(self) -> None:
        assert clean_user_text("foo\n\tbar\r\nbaz") == "foo bar baz"


class TestFormatUserText:
    def test_escaped_n_becomes_real_newline(self) -> None:
        from phoenix_scraper.normalize import format_user_text

        assert format_user_text(r"analyze UAXK\nand UZRZ journals\n") == (
            "analyze UAXK\nand UZRZ journals"
        )


class TestExtractUserPrompt:
    def test_plain_question_unchanged(self) -> None:
        q = "Why is there a recon break of 100k on CDS_IG_NY?"
        assert extract_user_prompt(q) == q

    def test_user_query_marker(self) -> None:
        blob = (
            "You are FOBO.\n\nUSER QUERY: Why did the break appear?\n\n"
            "Respond with JSON."
        )
        assert extract_user_prompt(blob) == "Why did the break appear?"

    def test_user_query_with_escaped_newlines(self) -> None:
        blob = r"SYSTEM\n\nUSER QUERY: analyze UAXK\nand UZRZ journals\n\nRespond"
        assert extract_user_prompt(blob) == "analyze UAXK\nand UZRZ journals"

    def test_bedrock_messages_json(self) -> None:
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [
                {"role": "user", "content": [{"text": "Show FX breaks over 100k"}]}
            ],
        }
        assert extract_user_prompt(json.dumps(payload)) == "Show FX breaks over 100k"

    def test_display_title_keeps_real_newlines(self) -> None:
        title = display_title("ask line 1\nline 2\\nline 3")
        assert "\\" not in title
        assert title == "ask line 1\nline 2\nline 3"


class TestDeterministicShape:
    def test_mcp_tool_select(self) -> None:
        text = "{'query': 'select:mcp__data-analysis__query_data', 'sql': 'select 1'}"
        assert is_deterministic_shaped(text) is True
        assert is_skill_shaped(text) is False

    def test_sql_with_session_id(self) -> None:
        sql = "SELECT * FROM breaks WHERE session_id = 'abc' AND amount > 100;"
        assert is_deterministic_shaped(sql) is True

    def test_file_path_blob(self) -> None:
        blob = json.dumps(
            {
                "file_path": "s3://bucket/uploads/breaks.csv",
                "document_id": "doc-123",
            }
        )
        assert is_deterministic_shaped(blob) is True

    def test_fobo_endpoint_params(self) -> None:
        blob = json.dumps(
            {
                "endpoint": "/fobo/breaks",
                "parameters": {"desk": "rates", "min_amount": 100000},
            }
        )
        assert is_deterministic_shaped(blob) is True

    def test_bedrock_without_user_query_is_deterministic(self) -> None:
        blob = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "system": [{"text": "tool router only"}],
                "messages": [],
            }
        )
        assert is_deterministic_shaped(blob) is True

    def test_bedrock_with_user_query_is_skill(self) -> None:
        blob = (
            '{"anthropic_version":"bedrock-2023-05-31","system":'
            '[{"text":"USER QUERY: Why is recon unmatched?"}],'
            '"messages":[]}'
        )
        assert is_skill_shaped(blob) is True
        assert "Why is recon unmatched?" in display_title(blob)

    def test_natural_question_is_skill(self) -> None:
        assert is_skill_shaped("Draft sign-off commentary for the rates desk") is True
        assert is_deterministic_shaped("Draft sign-off commentary for the rates desk") is False


class TestSqlKeywordOpeners:
    """A leading SQL *word* is not SQL. Real prompts open with Explain/Update/
    Select/Create/Drop all the time; they belong in the promote-to-skill lane."""

    PROSE = (
        "Explain the top PLEX drivers for credit on 2026-09-08",
        "Explain why the FX book broke overnight",
        "Update me on the rates desk exposure",
        "Select the best hedge for this position",
        "Create a summary of yesterday's PLEX attribution",
        "Drop me a note on the unmatched tickets",
        "Delete is too strong — just archive the stale breaks",
        "Insert the commentary into the sign-off pack",
        "Alter the tolerance so small breaks stop paging us",
        "With the desk closed, explain the residual",
    )

    REAL_SQL = (
        "EXPLAIN SELECT * FROM breaks",
        "SELECT book, amount FROM recon_breaks WHERE amount > 100",
        "UPDATE breaks SET status = 'closed'",
        "CREATE TABLE breaks (id TEXT)",
        "DROP TABLE breaks",
        "DELETE FROM breaks WHERE id = 1",
        "INSERT INTO breaks VALUES (1)",
        "ALTER TABLE breaks ADD COLUMN note TEXT",
        "PRAGMA table_info(breaks)",
        "WITH recent AS (SELECT 1) SELECT * FROM recent",
    )

    def test_prose_openers_are_skill_shaped(self) -> None:
        for text in self.PROSE:
            assert is_skill_shaped(text) is True, text
            assert is_deterministic_shaped(text) is False, text

    def test_real_sql_is_still_deterministic(self) -> None:
        for text in self.REAL_SQL:
            assert is_deterministic_shaped(text) is True, text
            assert is_skill_shaped(text) is False, text


class TestSpanLaneSplit:
    def test_llm_question_is_user_ask_not_deterministic_source(self) -> None:
        q = "Why is there an FX recon break?"
        assert is_user_ask_span("LLM", q) is True
        assert is_deterministic_source_span("LLM", q) is False

    def test_mcp_tool_span_is_deterministic_source(self) -> None:
        mcp = "{'query': 'select:mcp__data-analysis__query_data'}"
        assert is_user_ask_span("TOOL", mcp) is False
        assert is_deterministic_source_span("TOOL", mcp) is True
        assert is_user_ask_span("LLM", mcp) is False
        assert is_deterministic_source_span("LLM", mcp) is True

    def test_filter_splits_mixed_frame(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "span_id": "u1",
                    "span_kind": "LLM",
                    "input_text": "Why is there a recon break?",
                    "trace_id": "t1",
                },
                {
                    "span_id": "m1",
                    "span_kind": "TOOL",
                    "input_text": "select:mcp__data-analysis__query_data",
                    "trace_id": "t1",
                },
                {
                    "span_id": "a1",
                    "span_kind": "LLM",
                    "input_text": json.dumps(
                        {
                            "anthropic_version": "bedrock-2023-05-31",
                            "system": [{"text": "router"}],
                            "messages": [],
                        }
                    ),
                    "trace_id": "t2",
                },
            ]
        )
        asks = filter_user_ask_spans(df)
        dets = filter_deterministic_source_spans(df)
        assert list(asks["span_id"]) == ["u1"]
        # TOOL child stays on Rung 2; orphan Bedrock LLM on its own trace is the
        # turn root and is excluded from both lanes (not a skill ask, not a tool).
        assert set(dets["span_id"]) == {"m1"}
        assert "a1" not in set(asks["span_id"]) | set(dets["span_id"])

    def test_expand_cluster_includes_same_trace(self) -> None:
        df = pd.DataFrame(
            [
                {"span_id": "tool-1", "trace_id": "tr-9", "span_kind": "TOOL"},
                {"span_id": "llm-1", "trace_id": "tr-9", "span_kind": "LLM"},
                {"span_id": "other", "trace_id": "tr-8", "span_kind": "LLM"},
            ]
        )
        expanded = expand_cluster_trace_members(df, ("tool-1",))
        assert set(expanded["span_id"]) == {"tool-1", "llm-1"}
