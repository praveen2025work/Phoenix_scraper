"""Tests for tool-path signatures, outliers, llm messages, and ladder annotations."""

from datetime import UTC, datetime

import pandas as pd

from phoenix_scraper import annotations, ladder, outliers
from phoenix_scraper.cluster import build_clusters
from phoenix_scraper.config import Settings
from phoenix_scraper.llm_messages import prefer_messages_io
from phoenix_scraper.models import (
    Candidate,
    Capability,
    CapabilityFilter,
    PromptCluster,
    SpanRecord,
)
from phoenix_scraper.prompt_shape import filter_deterministic_source_spans
from phoenix_scraper.scraper import flatten_phoenix_row
from phoenix_scraper.storage import Store
from phoenix_scraper.tool_paths import (
    merge_deterministic_sources,
    tool_path_cluster_frame,
    tool_path_signature,
)

TS = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


def _span_row(**over) -> dict:
    base = {
        "span_id": "s1",
        "trace_id": "t1",
        "session_id": "sess-1",
        "name": "tool",
        "span_kind": "TOOL",
        "start_time": TS,
        "input_text": "",
        "output_text": "",
        "status_code": "OK",
        "cost_usd": 0.01,
        "latency_ms": 100.0,
        "tokens_total": 10,
        "user_id": "u1",
        "attributes": {},
    }
    base.update(over)
    return base


class TestToolPaths:
    def test_signature_orders_and_collapses(self) -> None:
        df = pd.DataFrame(
            [
                _span_row(
                    span_id="a",
                    name="query",
                    attributes={"tool.name": "mcp__data__query"},
                    start_time=TS,
                ),
                _span_row(
                    span_id="b",
                    name="query",
                    attributes={"tool.name": "mcp__data__query"},
                    start_time=TS.replace(second=1),
                ),
                _span_row(
                    span_id="c",
                    name="journals",
                    attributes={"tool.name": "mcp__fobo__journals"},
                    start_time=TS.replace(second=2),
                ),
                _span_row(
                    span_id="llm",
                    span_kind="LLM",
                    name="think",
                    start_time=TS.replace(second=3),
                    input_text="plan",
                ),
            ]
        )
        assert tool_path_signature(df) == "mcp__data__query ×2 → mcp__fobo__journals"

    def test_cluster_frame_one_row_per_trace(self) -> None:
        df = pd.DataFrame(
            [
                _span_row(
                    span_id="t1-tool",
                    trace_id="tr-a",
                    attributes={"tool.name": "query_data"},
                ),
                _span_row(
                    span_id="t1-tool2",
                    trace_id="tr-a",
                    attributes={"tool.name": "get_journals"},
                    start_time=TS.replace(second=1),
                ),
                _span_row(
                    span_id="t2-tool",
                    trace_id="tr-b",
                    session_id="sess-2",
                    attributes={"tool.name": "query_data"},
                ),
                _span_row(
                    span_id="t2-tool2",
                    trace_id="tr-b",
                    session_id="sess-2",
                    attributes={"tool.name": "get_journals"},
                    start_time=TS.replace(second=1),
                ),
            ]
        )
        paths = tool_path_cluster_frame(df)
        assert len(paths) == 2
        assert set(paths["input_text"]) == {"query_data → get_journals"}
        clusters = build_clusters(paths, fuzz_threshold=90)
        assert len(clusters) == 1
        assert clusters[0].count == 2
        assert "query_data" in clusters[0].representative
        assert "query data" in clusters[0].signature

    def test_merge_drops_tool_payloads_already_on_path(self) -> None:
        df = pd.DataFrame(
            [
                _span_row(
                    span_id="tool",
                    attributes={"tool.name": "query_data"},
                    input_text="select:mcp__data__query_data",
                ),
                _span_row(
                    span_id="llm-det",
                    span_kind="LLM",
                    input_text='{"endpoint": "/x", "parameters": {"a": 1}}',
                    name="invoke",
                ),
            ]
        )
        payload = filter_deterministic_source_spans(df)
        merged = merge_deterministic_sources(df, payload)
        kinds = list(merged["span_kind"])
        texts = list(merged["input_text"])
        assert any("query_data" == t or "query_data" in t for t in texts)
        # TOOL payload row should not also appear alongside the path row.
        assert sum(1 for k in kinds if k == "TOOL") == 1


class TestOutliers:
    def test_error_and_heavy_tool_turns_surface(self) -> None:
        rows = []
        for i in range(8):
            rows.append(
                _span_row(
                    span_id=f"root-{i}",
                    trace_id=f"tr-{i}",
                    session_id=f"s-{i}",
                    span_kind="CHAIN",
                    name="agent_request",
                    parent_id=None,
                    input_text=f"ask {i}",
                    latency_ms=100.0 + i,
                    cost_usd=0.01,
                )
            )
            rows.append(
                _span_row(
                    span_id=f"tool-{i}",
                    trace_id=f"tr-{i}",
                    session_id=f"s-{i}",
                    attributes={"tool.name": "q"},
                    latency_ms=50.0,
                    parent_id=f"root-{i}",
                )
            )
        # Outlier: many tools + error
        for j in range(6):
            rows.append(
                _span_row(
                    span_id=f"heavy-{j}",
                    trace_id="tr-heavy",
                    session_id="s-heavy",
                    attributes={"tool.name": f"t{j}"},
                    status_code="ERROR" if j == 0 else "OK",
                    latency_ms=5000.0,
                    cost_usd=1.0,
                    parent_id="root-heavy",
                )
            )
        rows.append(
            _span_row(
                span_id="root-heavy",
                trace_id="tr-heavy",
                session_id="s-heavy",
                span_kind="CHAIN",
                name="agent_request",
                parent_id=None,
                input_text="analyze journals",
                latency_ms=9000.0,
                cost_usd=0.5,
            )
        )
        df = pd.DataFrame(rows)
        out = outliers.turn_outliers(df, quantile=0.8, min_tools_for_heavy=4)
        assert not out.empty
        assert "tr-heavy" in set(out["trace_id"].astype(str))
        assert out.iloc[0]["triage_score"] >= 1


class TestLlmMessages:
    def test_prefer_nested_messages_over_input_value(self) -> None:
        attrs = {
            "llm": {
                "input_messages": [
                    {"role": "system", "content": "You are FOBO"},
                    {"role": "user", "content": "analyze UAXK journals"},
                ],
                "output_messages": [
                    {"role": "assistant", "content": "Here is the break list"},
                ],
            },
            "input": {"value": '{"anthropic_version": "bedrock"}'},
            "output": {"value": "raw"},
        }
        inp, out = prefer_messages_io(
            attributes=attrs,
            input_value='{"anthropic_version": "bedrock"}',
            output_value="raw",
        )
        assert inp == "analyze UAXK journals"
        assert out == "Here is the break list"

    def test_flatten_phoenix_row_uses_flat_message_columns(self) -> None:
        row = {
            "context.span_id": "msg-1",
            "context.trace_id": "tr-1",
            "name": "ChatCompletion",
            "span_kind": "LLM",
            "start_time": TS.isoformat(),
            "status_code": "OK",
            "attributes.openinference.span.kind": "LLM",
            "attributes.input.value": '{"anthropic_version":"x"}',
            "attributes.output.value": "blob",
            "attributes.llm.input_messages.0.message.role": "user",
            "attributes.llm.input_messages.0.message.content": "Why is EURUSD broken?",
            "attributes.llm.output_messages.0.message.role": "assistant",
            "attributes.llm.output_messages.0.message.content": "Unsettled trade",
        }
        record = flatten_phoenix_row(row, "pnl-agent")
        assert record is not None
        assert record.input_text == "Why is EURUSD broken?"
        assert record.output_text == "Unsettled trade"


class TestFrictionBoost:
    def test_high_friction_raises_rung1_score(self) -> None:
        clusters = [
            PromptCluster(
                cluster_id="aaa",
                signature="why break",
                representative="why is there a break",
                count=20,
                n_users=5,
                n_sessions=5,
                total_cost_usd=1.0,
                span_ids=("s1", "s2"),
            )
        ]
        t = ladder.resolve_thresholds(
            Capability(
                id="fobo",
                name="FOBO",
                filter=CapabilityFilter(workflow_stage="fobo_recon"),
            ),
            Settings(_env_file=None, db_path="x.db"),
        )
        annotated = pd.DataFrame(
            columns=[
                "cluster_id", "skill_name", "representative", "signature",
                "count", "n_users", "coverage_score", "covered",
            ]
        )
        efficiency = pd.DataFrame(
            [{"cluster_id": "aaa", "route_len_avg": 3.0, "long_route": False}]
        )
        plain = ladder.detect_rung1(
            clusters, [], annotated, efficiency, thresholds=t
        )
        boosted = ladder.detect_rung1(
            clusters,
            [],
            annotated,
            efficiency,
            thresholds=t,
            friction_by_session={"sess-a": 10.0},
            outlier_traces=frozenset({"tr-a"}),
            span_to_session={"s1": "sess-a"},
            span_to_trace={"s1": "tr-a"},
        )
        assert plain[0].score == 1.0  # already capped
        assert boosted[0].priority_boost > 0
        assert boosted[0].friction_score == 10.0
        assert boosted[0].outlier_hits == 1


class FakePhoenix:
    def __init__(self) -> None:
        self.pushed: list[dict] = []

    def available(self) -> bool:
        return True

    def push_span_annotations(self, project: str, payload) -> int:
        self.pushed.extend(payload)
        return len(payload)


class TestLadderDecisionAnnotations:
    def test_push_promote_uses_member_spans(self, tmp_path) -> None:
        store = Store(tmp_path / "t.db")
        settings = Settings(_env_file=None, db_path=tmp_path / "t.db", project="pnl")
        store.upsert_spans(
            [
                SpanRecord(
                    span_id="sp-1",
                    trace_id="tr-1",
                    project="pnl",
                    span_kind="CHAIN",
                    start_time=TS,
                    input_text="ask",
                )
            ]
        )
        # Minimal capability run + member row
        from phoenix_scraper.models import CapabilityRun

        run = CapabilityRun(
            capability_id="fobo",
            run_id="2026-08-07T12:00:00+00:00",
            started_at=TS,
            finished_at=TS,
            window_start=TS,
            window_end=TS,
            n_spans=1,
            n_in_scope_spans=1,
            n_clusters=1,
            status="ok",
        )
        store.record_capability_run(
            run,
            snapshot_rows=[
                {
                    "capability_id": "fobo",
                    "run_id": run.run_id,
                    "cluster_id": "clu1",
                    "signature": "why break",
                    "representative": "why break",
                    "count": 1,
                    "n_users": 1,
                    "skill_name": None,
                    "covered": 0,
                    "in_scope": 1,
                    "route_len_avg": None,
                    "long_route": 0,
                    "first_seen": None,
                    "last_seen": None,
                    "asset_classes": "[]",
                }
            ],
            member_rows=[("clu1", "sp-1")],
            history_limit=5,
        )
        cand = Candidate(
            candidate_id="fobo:s:clu1",
            capability_id="fobo",
            rung="skill",
            cluster_id="clu1",
            title="why break",
            signature="why break",
            status="accepted",
            first_seen_run_id=run.run_id,
            first_seen_at=TS,
            last_seen_run_id=run.run_id,
            last_seen_at=TS,
        )
        client = FakePhoenix()
        report = annotations.push_ladder_decision(
            store, client, settings, cand, "promote", actor="alice"
        )
        assert report.stored == 1
        assert client.pushed[0]["name"] == "skillgap.decision"
        assert client.pushed[0]["result"]["label"] == "promote"
        assert client.pushed[0]["span_id"] == "sp-1"
        store.close()
