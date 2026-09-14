"""Tests for skill vs deterministic prompt-shape classification."""

import json

from phoenix_scraper.prompt_shape import (
    display_title,
    extract_user_prompt,
    is_deterministic_shaped,
    is_skill_shaped,
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

    def test_bedrock_messages_json(self) -> None:
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [
                {"role": "user", "content": [{"text": "Show FX breaks over 100k"}]}
            ],
        }
        assert extract_user_prompt(json.dumps(payload)) == "Show FX breaks over 100k"


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
