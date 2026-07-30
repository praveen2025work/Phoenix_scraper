"""Shared test fixtures: an in-temp store, sample spans, and catalog paths."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from phoenix_scraper.config import Settings
from phoenix_scraper.models import SpanRecord
from phoenix_scraper.storage import Store

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_TS = datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC)


def make_span(i: int, **overrides) -> SpanRecord:
    defaults = dict(
        span_id=f"span-{i:04d}",
        trace_id=f"trace-{i // 2:04d}",
        session_id=f"sess-{i // 4:03d}",
        project="pnl-agent",
        name="llm-call",
        span_kind="LLM",
        start_time=BASE_TS + timedelta(minutes=i),
        end_time=BASE_TS + timedelta(minutes=i, seconds=3),
        latency_ms=3000.0,
        model_name="us.anthropic.claude-sonnet-4-6",
        user_id=f"analyst-{i % 3}",
        workflow_stage="fobo_recon",
        asset_class="fx",
        input_text=f"Why is there an FX recon break of {100 + i}k on EURUSD?",
        output_text="Because of an unsettled trade.",
        tokens_prompt=200,
        tokens_completion=80,
        tokens_total=280,
        cost_usd=None,
        attributes={},
    )
    defaults.update(overrides)
    return SpanRecord(**defaults)


@pytest.fixture()
def sample_spans() -> list[SpanRecord]:
    spans = [make_span(i) for i in range(8)]
    spans.append(
        make_span(
            8,
            span_kind="TOOL",
            input_text="",
            workflow_stage="adjustments",
            attributes={"tool.name": "adjustment_poster"},
        )
    )
    spans.append(
        make_span(
            9,
            workflow_stage="commentary_signoff",
            asset_class="rates",
            input_text="Draft sign-off commentary for the rates desk",
        )
    )
    return spans


@pytest.fixture()
def tmp_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture()
def seeded_store(tmp_store: Store, sample_spans: list[SpanRecord]) -> Store:
    tmp_store.upsert_spans(sample_spans)
    return tmp_store


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        export_dir=tmp_path / "exports",
        skills_catalog=REPO_ROOT / "config" / "skills_catalog.yaml",
        pricing_path=REPO_ROOT / "config" / "pricing.yaml",
    )
