"""Tests for phoenix_scraper.sessions.derive_sessions."""

from datetime import UTC, datetime, timedelta

import pandas as pd
from conftest import BASE_TS, make_span

from phoenix_scraper.models import QueryFilters, SessionRecord
from phoenix_scraper.sessions import derive_sessions
from phoenix_scraper.storage import Store


def _frame(store: Store, spans) -> pd.DataFrame:
    store.upsert_spans(spans)
    return store.spans_frame(QueryFilters(limit=10_000))


def test_returns_empty_list_for_empty_frame(tmp_store: Store) -> None:
    assert derive_sessions(tmp_store.spans_frame()) == []


def test_multi_session_grouping(seeded_store: Store) -> None:
    df = seeded_store.spans_frame()
    sessions = derive_sessions(df)
    # sample_spans: i//4 -> sess-000 (0-3), sess-001 (4-7), sess-002 (8-9)
    assert {s.session_id for s in sessions} == {"sess-000", "sess-001", "sess-002"}
    assert all(isinstance(s, SessionRecord) for s in sessions)
    by_id = {s.session_id: s for s in sessions}
    assert by_id["sess-000"].n_llm_spans == 4
    assert by_id["sess-000"].n_traces == 2  # trace-0000, trace-0001
    assert by_id["sess-000"].project == "pnl-agent"


def test_null_and_empty_session_ids_dropped(tmp_store: Store) -> None:
    spans = [
        make_span(0),
        make_span(1, session_id=None),
        make_span(2, session_id=""),
    ]
    sessions = derive_sessions(_frame(tmp_store, spans))
    assert [s.session_id for s in sessions] == ["sess-000"]
    assert sessions[0].n_llm_spans == 1


def test_turn_token_and_cost_aggregation(tmp_store: Store) -> None:
    spans = [
        make_span(0, session_id="s1", tokens_total=100, cost_usd=0.5),
        make_span(1, session_id="s1", tokens_total=None, cost_usd=None),
        # TOOL span: not an LLM span, not a user turn, tokens still summed (None -> 0)
        make_span(
            2,
            session_id="s1",
            span_kind="TOOL",
            input_text="",
            tokens_total=None,
            cost_usd=0.25,
        ),
        # LLM span with empty input_text: counts as LLM span but not a user turn
        make_span(3, session_id="s1", input_text="", tokens_total=40, cost_usd=None),
    ]
    (session,) = derive_sessions(_frame(tmp_store, spans))
    assert session.n_llm_spans == 3
    assert session.n_user_turns == 2
    assert session.total_tokens == 140
    assert session.total_cost_usd == 0.75


def test_first_prompt_is_earliest_llm_input_text(tmp_store: Store) -> None:
    spans = [
        # TOOL span earliest of all — must be ignored for first_prompt
        make_span(
            0,
            session_id="s1",
            span_kind="TOOL",
            input_text="tool payload",
            start_time=BASE_TS - timedelta(minutes=5),
        ),
        make_span(
            1,
            session_id="s1",
            input_text="second prompt",
            start_time=BASE_TS + timedelta(minutes=1),
        ),
        make_span(2, session_id="s1", input_text="first prompt", start_time=BASE_TS),
    ]
    (session,) = derive_sessions(_frame(tmp_store, spans))
    assert session.first_prompt == "first prompt"
    # session window covers all rows including the TOOL span
    assert session.start_time == datetime(2026, 7, 20, 8, 55, tzinfo=UTC)


def test_models_sorted_distinct_from_model_name_column(tmp_store: Store) -> None:
    spans = [
        make_span(0, session_id="s1", model_name="model-b"),
        make_span(1, session_id="s1", model_name="model-a"),
        make_span(2, session_id="s1", model_name="model-b"),
        make_span(3, session_id="s1", model_name=None, span_kind="TOOL", input_text=""),
    ]
    (session,) = derive_sessions(_frame(tmp_store, spans))
    assert session.models == ("model-a", "model-b")


def test_user_id_first_non_null(tmp_store: Store) -> None:
    spans = [
        make_span(0, session_id="s1", user_id=None),
        make_span(1, session_id="s1", user_id="analyst-7"),
        make_span(2, session_id="s1", user_id="analyst-9"),
    ]
    (session,) = derive_sessions(_frame(tmp_store, spans))
    assert session.user_id == "analyst-7"


def test_end_time_is_max_and_input_unmutated(tmp_store: Store) -> None:
    spans = [
        make_span(0, session_id="s1"),
        make_span(5, session_id="s1"),
    ]
    df = _frame(tmp_store, spans)
    snapshot = df.copy(deep=True)
    (session,) = derive_sessions(df)
    assert session.start_time == BASE_TS
    assert session.end_time == BASE_TS + timedelta(minutes=5, seconds=3)
    pd.testing.assert_frame_equal(df, snapshot)
