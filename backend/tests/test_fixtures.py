"""Tests for fixtures.py — deterministic synthetic P&L-agent traffic."""

from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from phoenix_scraper.fixtures import (
    HOT_TEMPLATES,
    generate_fixture_spans,
    seed_demo,
)
from phoenix_scraper.models import SpanRecord
from phoenix_scraper.storage import Store

EXPECTED_ASSET_CLASSES = {"fx", "rates", "equities", "credit"}
EXPECTED_STAGES = {
    "fobo_recon",
    "plex",
    "flash_vs_formal",
    "adjustments",
    "commentary_signoff",
}
ALLOWED_MODELS = {
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-haiku-4-5",
}


@pytest.fixture(scope="module")
def spans() -> list[SpanRecord]:
    return generate_fixture_spans()


def llm_spans(records: list[SpanRecord]) -> list[SpanRecord]:
    return [r for r in records if r.span_kind == "LLM"]


# ---- determinism -------------------------------------------------------------


def test_deterministic_under_seed() -> None:
    a = generate_fixture_spans(n_sessions=10, seed=7)
    b = generate_fixture_spans(n_sessions=10, seed=7)
    assert a == b


def test_different_seed_differs() -> None:
    a = generate_fixture_spans(n_sessions=10, seed=1)
    b = generate_fixture_spans(n_sessions=10, seed=2)
    assert [s.input_text for s in llm_spans(a)] != [s.input_text for s in llm_spans(b)]


def test_no_input_mutation_between_calls(spans: list[SpanRecord]) -> None:
    # frozen pydantic models: attempting mutation raises
    with pytest.raises(ValidationError):
        spans[0].input_text = "changed"  # type: ignore[misc]


# ---- structure & coverage ----------------------------------------------------


def test_session_count_and_project(spans: list[SpanRecord]) -> None:
    sessions = {s.session_id for s in spans}
    assert len(sessions) == 60
    assert all(s.project == "pnl-agent" for s in spans)
    assert all(s.session_id for s in spans)
    assert all(s.trace_id and s.span_id for s in spans)


def test_span_ids_unique(spans: list[SpanRecord]) -> None:
    ids = [s.span_id for s in spans]
    assert len(ids) == len(set(ids))


def test_asset_class_coverage(spans: list[SpanRecord]) -> None:
    assert {s.asset_class for s in llm_spans(spans)} >= EXPECTED_ASSET_CLASSES


def test_stage_coverage(spans: list[SpanRecord]) -> None:
    assert {s.workflow_stage for s in llm_spans(spans)} >= EXPECTED_STAGES


def test_analyst_pool(spans: list[SpanRecord]) -> None:
    users = {s.user_id for s in spans if s.user_id}
    assert 6 <= len(users) <= 10


# ---- prompt distribution -----------------------------------------------------


def test_hot_templates_repeat(spans: list[SpanRecord]) -> None:
    assert len(HOT_TEMPLATES) >= 10
    by_template = Counter(
        s.prompt_template for s in llm_spans(spans) if s.prompt_template
    )
    for template in HOT_TEMPLATES:
        assert by_template[template] >= 8, template


def test_hot_templates_have_varying_instantiations(spans: list[SpanRecord]) -> None:
    texts_by_template: dict[str, set[str]] = {}
    for s in llm_spans(spans):
        if s.prompt_template:
            texts_by_template.setdefault(s.prompt_template, set()).add(s.input_text)
    varying = [t for t, texts in texts_by_template.items() if len(texts) > 1]
    assert len(varying) >= 5


def test_long_tail_one_offs(spans: list[SpanRecord]) -> None:
    tail = [s.input_text for s in llm_spans(spans) if s.prompt_template is None]
    counts = Counter(tail)
    one_offs = [text for text, n in counts.items() if n == 1]
    assert len(one_offs) >= 25


def test_long_tail_includes_no_skill_prompts(spans: list[SpanRecord]) -> None:
    tail = " ".join(
        s.input_text.lower() for s in llm_spans(spans) if s.prompt_template is None
    )
    assert "translate" in tail
    assert "email" in tail


# ---- LLM span realism ----------------------------------------------------------


def test_llm_spans_have_tokens_models_and_no_cost(spans: list[SpanRecord]) -> None:
    llms = llm_spans(spans)
    assert llms
    for s in llms:
        assert s.model_name in ALLOWED_MODELS
        assert s.cost_usd is None
        assert s.tokens_prompt and s.tokens_prompt > 0
        assert s.tokens_completion and s.tokens_completion > 0
        assert s.tokens_total == s.tokens_prompt + s.tokens_completion
        assert s.input_text.strip()


def test_sonnet_is_majority(spans: list[SpanRecord]) -> None:
    models = Counter(s.model_name for s in llm_spans(spans))
    assert models["us.anthropic.claude-sonnet-4-6"] > models[
        "us.anthropic.claude-haiku-4-5"
    ]
    assert models["us.anthropic.claude-haiku-4-5"] > 0


# ---- agent/tool child spans ----------------------------------------------------


def test_agent_and_tool_spans_present(spans: list[SpanRecord]) -> None:
    agents = [s for s in spans if s.span_kind == "AGENT"]
    tools = [s for s in spans if s.span_kind == "TOOL"]
    n_turns = len(llm_spans(spans))
    assert len(agents) == len(tools)
    # ~30% of turns emit AGENT+TOOL children
    assert 0.15 * n_turns <= len(tools) <= 0.45 * n_turns
    for t in tools:
        assert "tool.name" in t.attributes
        assert t.attributes["tool.name"]


def test_tool_names_consistent_with_stage(spans: list[SpanRecord]) -> None:
    tool_names_by_stage: dict[str, set[str]] = {}
    for t in (s for s in spans if s.span_kind == "TOOL"):
        assert t.workflow_stage in EXPECTED_STAGES
        tool_names_by_stage.setdefault(t.workflow_stage, set()).add(
            t.attributes["tool.name"]
        )
    # each stage maps to a single deterministic tool
    for names in tool_names_by_stage.values():
        assert len(names) == 1


# ---- timestamps ----------------------------------------------------------------


def test_timestamps_recent_and_utc(spans: list[SpanRecord]) -> None:
    now = datetime.now(UTC)
    for s in spans:
        assert s.start_time.tzinfo is not None
        assert s.start_time.utcoffset() == timedelta(0)
        assert now - timedelta(days=14) <= s.start_time <= now
        if s.end_time is not None:
            assert s.end_time >= s.start_time


# ---- seed_demo -------------------------------------------------------------------


def test_seed_demo_inserts_and_reports(tmp_store: Store) -> None:
    expected = generate_fixture_spans(n_sessions=5, seed=3)
    report = seed_demo(tmp_store, n_sessions=5, seed=3)
    assert report.source == "fixtures"
    assert report.pulled == len(expected)
    assert report.inserted == len(expected)
    assert report.skipped == 0
    assert report.watermark_before is None
    assert report.watermark_after == max(s.start_time for s in expected)
    df = tmp_store.spans_frame()
    assert len(df) == len(expected)


def test_seed_demo_idempotent(tmp_store: Store) -> None:
    first = seed_demo(tmp_store, n_sessions=5, seed=3)
    second = seed_demo(tmp_store, n_sessions=5, seed=3)
    assert second.pulled == first.pulled
    assert second.inserted == 0
    assert second.skipped == second.pulled
    assert second.watermark_before == first.watermark_after
