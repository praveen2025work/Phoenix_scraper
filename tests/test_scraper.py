"""Tests for phoenix_client.PhoenixClientWrapper and scraper (flatten/scrape/ingest)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import phoenix_scraper.phoenix_client as phoenix_client_module
from phoenix_scraper.config import Settings
from phoenix_scraper.phoenix_client import PhoenixClientWrapper, build_tls_verify
from phoenix_scraper.scraper import flatten_phoenix_row, ingest_jsonl, scrape_once
from phoenix_scraper.storage import Store

BASE_TS = datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC)
PROJECT = "pnl-agent"


def flat_row(i: int = 0, **overrides) -> dict:
    """A Phoenix row in flattened-column form (as get_spans_dataframe returns)."""
    row = {
        "context.span_id": f"px-span-{i:04d}",
        "context.trace_id": f"px-trace-{i:04d}",
        "name": "ChatCompletion",
        "span_kind": "LLM",
        "start_time": (BASE_TS + timedelta(minutes=i)).isoformat(),
        "end_time": (BASE_TS + timedelta(minutes=i, seconds=2)).isoformat(),
        "status_code": "OK",
        "attributes.openinference.span.kind": "LLM",
        "attributes.session.id": f"sess-{i:03d}",
        "attributes.user.id": "analyst-1",
        "attributes.llm.model_name": "us.anthropic.claude-sonnet-4-6",
        "attributes.llm.token_count.prompt": 120,
        "attributes.llm.token_count.completion": 40,
        "attributes.llm.token_count.total": 160,
        "attributes.input.value": "Why is there a 250k break on EURUSD?",
        "attributes.output.value": "Unsettled trade.",
        "attributes.metadata.workflow_stage": "fobo_recon",
        "attributes.metadata.asset_class": "fx",
    }
    row.update(overrides)
    return row


def nested_row(i: int = 0) -> dict:
    """The same span expressed with a nested attributes dict (jsonl export form)."""
    return {
        "context": {"span_id": f"px-span-{i:04d}", "trace_id": f"px-trace-{i:04d}"},
        "name": "ChatCompletion",
        "start_time": (BASE_TS + timedelta(minutes=i)).isoformat(),
        "end_time": (BASE_TS + timedelta(minutes=i, seconds=2)).isoformat(),
        "status_code": "OK",
        "attributes": {
            "openinference": {"span": {"kind": "LLM"}},
            "session": {"id": f"sess-{i:03d}"},
            "user": {"id": "analyst-1"},
            "llm": {
                "model_name": "us.anthropic.claude-sonnet-4-6",
                "token_count": {"prompt": 120, "completion": 40, "total": 160},
                "cost": {"total": 0.0123},
            },
            "input": {"value": "Why is there a 250k break on EURUSD?"},
            "output": {"value": "Unsettled trade."},
            "metadata": {"workflow_stage": "fobo_recon", "asset_class": "fx"},
        },
    }


def make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "test.db", **kwargs)


@pytest.fixture(autouse=True)
def _clean_phoenix_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("PHOENIX_CLIENT_HEADERS", raising=False)


# ---------------------------------------------------------------------------
# flatten_phoenix_row
# ---------------------------------------------------------------------------
class TestFlattenPhoenixRow:
    def test_flat_columns_mapped(self) -> None:
        record = flatten_phoenix_row(flat_row(7), PROJECT)

        assert record is not None
        assert record.span_id == "px-span-0007"
        assert record.trace_id == "px-trace-0007"
        assert record.session_id == "sess-007"
        assert record.user_id == "analyst-1"
        assert record.project == PROJECT
        assert record.span_kind == "LLM"
        assert record.model_name == "us.anthropic.claude-sonnet-4-6"
        assert record.tokens_prompt == 120
        assert record.tokens_completion == 40
        assert record.tokens_total == 160
        assert record.input_text == "Why is there a 250k break on EURUSD?"
        assert record.output_text == "Unsettled trade."
        assert record.workflow_stage == "fobo_recon"
        assert record.asset_class == "fx"
        assert record.start_time == BASE_TS + timedelta(minutes=7)
        assert record.start_time.tzinfo is not None

    def test_nested_attributes_mapped(self) -> None:
        record = flatten_phoenix_row(nested_row(3), PROJECT)

        assert record is not None
        assert record.span_id == "px-span-0003"
        assert record.trace_id == "px-trace-0003"
        assert record.session_id == "sess-003"
        assert record.span_kind == "LLM"
        assert record.model_name == "us.anthropic.claude-sonnet-4-6"
        assert record.tokens_prompt == 120
        assert record.cost_usd == pytest.approx(0.0123)
        assert record.input_text == "Why is there a 250k break on EURUSD?"
        assert record.workflow_stage == "fobo_recon"
        assert record.asset_class == "fx"

    @pytest.mark.parametrize("missing_key", ["context.span_id", "context.trace_id", "start_time"])
    def test_missing_required_field_returns_none(self, missing_key: str) -> None:
        row = {k: v for k, v in flat_row().items() if k != missing_key}
        assert flatten_phoenix_row(row, PROJECT) is None

    def test_nan_span_id_returns_none(self) -> None:
        assert flatten_phoenix_row(flat_row(**{"context.span_id": float("nan")}), PROJECT) is None

    def test_nan_optional_fields_become_none(self) -> None:
        row = flat_row(
            **{
                "attributes.session.id": float("nan"),
                "attributes.user.id": None,
                "attributes.llm.token_count.prompt": float("nan"),
                "attributes.llm.model_name": pd.NA,
                "attributes.input.value": float("nan"),
            }
        )
        record = flatten_phoenix_row(row, PROJECT)

        assert record is not None
        assert record.session_id is None
        assert record.user_id is None
        assert record.tokens_prompt is None
        assert record.model_name is None
        assert record.input_text == ""

    def test_naive_start_time_coerced_to_utc(self) -> None:
        record = flatten_phoenix_row(flat_row(start_time="2026-07-20T09:00:00"), PROJECT)
        assert record is not None
        assert record.start_time.tzinfo is not None
        assert record.start_time == BASE_TS

    def test_latency_computed_from_start_end(self) -> None:
        record = flatten_phoenix_row(flat_row(), PROJECT)
        assert record is not None
        assert record.latency_ms == pytest.approx(2000.0)

    def test_span_kind_defaults_to_unknown(self) -> None:
        row = flat_row()
        del row["attributes.openinference.span.kind"]
        del row["span_kind"]
        record = flatten_phoenix_row(row, PROJECT)
        assert record is not None
        assert record.span_kind == "UNKNOWN"

    def test_input_does_not_mutate_row(self) -> None:
        row = nested_row(1)
        snapshot = json.loads(json.dumps(row))
        flatten_phoenix_row(row, PROJECT)
        assert row == snapshot


# ---------------------------------------------------------------------------
# PhoenixClientWrapper (never hits the network — phoenix.client.Client is faked)
# ---------------------------------------------------------------------------
class FakeSpansAPI:
    def __init__(self, frames: list[pd.DataFrame], failures: int = 0) -> None:
        self.frames = list(frames)
        self.failures = failures
        self.calls: list[dict] = []

    def get_spans_dataframe(self, **kwargs) -> pd.DataFrame:
        self.calls.append(kwargs)
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("phoenix unreachable")
        return self.frames.pop(0)


class FakeClient:
    last_instance: "FakeClient | None" = None
    spans_api: FakeSpansAPI = FakeSpansAPI([pd.DataFrame()])

    def __init__(self, *, base_url=None, api_key=None, **kwargs) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.kwargs = kwargs
        self.spans = type(self).spans_api
        type(self).last_instance = self


@pytest.fixture()
def fake_phoenix(monkeypatch: pytest.MonkeyPatch):
    import phoenix.client

    monkeypatch.setattr(phoenix.client, "Client", FakeClient)
    sleeps: list[float] = []
    monkeypatch.setattr(
        phoenix_client_module, "time", SimpleNamespace(sleep=sleeps.append)
    )
    return sleeps


class TestPhoenixClientWrapper:
    def test_available_false_without_endpoint(self, tmp_path: Path) -> None:
        wrapper = PhoenixClientWrapper(make_settings(tmp_path))
        assert wrapper.available() is False

    def test_available_true_with_endpoint(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="http://phx:6006")
        wrapper = PhoenixClientWrapper(settings)
        assert wrapper.available() is True

    def test_fetch_spans_raises_runtime_error_when_unconfigured(self, tmp_path: Path) -> None:
        wrapper = PhoenixClientWrapper(make_settings(tmp_path))
        with pytest.raises(RuntimeError, match="PHOENIX_COLLECTOR_ENDPOINT"):
            wrapper.fetch_spans(PROJECT, None, None, 100)

    def test_fetch_spans_passes_connection_and_query_args(
        self, tmp_path: Path, fake_phoenix
    ) -> None:
        expected = pd.DataFrame([flat_row(0)])
        FakeClient.spans_api = FakeSpansAPI([expected])
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="http://phx:6006", PHOENIX_API_KEY="sekret"
        )
        wrapper = PhoenixClientWrapper(settings)
        start = BASE_TS - timedelta(hours=1)

        result = wrapper.fetch_spans(PROJECT, start, BASE_TS, 250)

        assert result.equals(expected)
        assert FakeClient.last_instance is not None
        assert FakeClient.last_instance.base_url == "http://phx:6006"
        assert FakeClient.last_instance.api_key == "sekret"
        call = FakeClient.spans_api.calls[0]
        assert call["start_time"] == start
        assert call["end_time"] == BASE_TS
        assert call["limit"] == 250
        assert call["project_identifier"] == PROJECT
        from phoenix.client.types.spans import SpanQuery

        assert isinstance(call["query"], SpanQuery)

    def test_fetch_spans_retries_on_connection_error(self, tmp_path: Path, fake_phoenix) -> None:
        expected = pd.DataFrame([flat_row(0)])
        FakeClient.spans_api = FakeSpansAPI([expected], failures=2)
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="http://phx:6006")
        wrapper = PhoenixClientWrapper(settings)

        result = wrapper.fetch_spans(PROJECT, None, None, 10)

        assert result.equals(expected)
        assert len(FakeClient.spans_api.calls) == 3
        assert len(fake_phoenix) == 2  # slept between attempts
        assert fake_phoenix[0] < fake_phoenix[1]  # backoff grows

    def test_fetch_spans_fails_after_three_attempts(self, tmp_path: Path, fake_phoenix) -> None:
        FakeClient.spans_api = FakeSpansAPI([], failures=99)
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="http://phx:6006")
        wrapper = PhoenixClientWrapper(settings)

        with pytest.raises(RuntimeError, match="3"):
            wrapper.fetch_spans(PROJECT, None, None, 10)
        assert len(FakeClient.spans_api.calls) == 3

    def test_fetch_spans_no_custom_http_client_by_default(
        self, tmp_path: Path, fake_phoenix, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)  # ensure no certs/phoenix-ca.pem is picked up
        FakeClient.spans_api = FakeSpansAPI([pd.DataFrame()])
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="http://phx:6006")

        PhoenixClientWrapper(settings).fetch_spans(PROJECT, None, None, 10)

        assert FakeClient.last_instance is not None
        assert FakeClient.last_instance.kwargs.get("http_client") is None

    def test_fetch_spans_uses_custom_http_client_for_timeout_override(
        self, tmp_path: Path, fake_phoenix, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx

        monkeypatch.chdir(tmp_path)  # no CA bundle in play — timeout alone triggers it
        FakeClient.spans_api = FakeSpansAPI([pd.DataFrame()])
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx:6006", http_timeout=120.0
        )

        PhoenixClientWrapper(settings).fetch_spans(PROJECT, None, None, 10)

        assert FakeClient.last_instance is not None
        http_client = FakeClient.last_instance.kwargs["http_client"]
        assert isinstance(http_client, httpx.Client)
        assert http_client.timeout.read == 120.0

    def test_fetch_spans_uses_custom_http_client_with_ca_bundle(
        self, tmp_path: Path, fake_phoenix
    ) -> None:
        import certifi
        import httpx

        FakeClient.spans_api = FakeSpansAPI([pd.DataFrame()])
        settings = make_settings(
            tmp_path,
            PHOENIX_COLLECTOR_ENDPOINT="https://phx:6006",
            PHOENIX_API_KEY="sekret",
            ca_bundle=certifi.where(),  # any real PEM stands in for the corp CA
        )

        PhoenixClientWrapper(settings).fetch_spans(PROJECT, None, None, 10)

        assert FakeClient.last_instance is not None
        http_client = FakeClient.last_instance.kwargs["http_client"]
        assert isinstance(http_client, httpx.Client)
        assert str(http_client.base_url).rstrip("/") == "https://phx:6006"
        assert http_client.headers["authorization"] == "Bearer sekret"
        assert http_client.is_closed  # no connection-pool leak per fetch

    def test_custom_http_client_carries_env_client_headers(
        self, tmp_path: Path, fake_phoenix, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import certifi
        import httpx

        monkeypatch.setenv("PHOENIX_CLIENT_HEADERS", "x-proxy-auth=abc123")
        FakeClient.spans_api = FakeSpansAPI([pd.DataFrame()])
        settings = make_settings(
            tmp_path,
            PHOENIX_COLLECTOR_ENDPOINT="https://phx:6006",
            ca_bundle=certifi.where(),
        )

        PhoenixClientWrapper(settings).fetch_spans(PROJECT, None, None, 10)

        assert FakeClient.last_instance is not None
        http_client = FakeClient.last_instance.kwargs["http_client"]
        assert isinstance(http_client, httpx.Client)
        assert http_client.headers["x-proxy-auth"] == "abc123"

    def test_custom_http_client_closed_even_when_all_retries_fail(
        self, tmp_path: Path, fake_phoenix
    ) -> None:
        import certifi

        FakeClient.spans_api = FakeSpansAPI([], failures=99)
        settings = make_settings(
            tmp_path,
            PHOENIX_COLLECTOR_ENDPOINT="https://phx:6006",
            ca_bundle=certifi.where(),
        )

        with pytest.raises(RuntimeError):
            PhoenixClientWrapper(settings).fetch_spans(PROJECT, None, None, 10)

        assert FakeClient.last_instance is not None
        assert FakeClient.last_instance.kwargs["http_client"].is_closed


class TestBlankEnvValues:
    def test_blank_strings_treated_as_unset(self, tmp_path: Path) -> None:
        # A shipped .env carries `PHOENIX_API_KEY=` etc. as empty strings; those
        # must behave exactly like the variable being absent.
        settings = make_settings(
            tmp_path,
            PHOENIX_COLLECTOR_ENDPOINT="",
            PHOENIX_API_KEY=" ",
            api_key="",
        )
        assert settings.phoenix_endpoint is None
        assert settings.phoenix_api_key is None
        assert settings.api_key is None


# ---------------------------------------------------------------------------
# TLS / corporate CA configuration
# ---------------------------------------------------------------------------
class TestResolvedCaBundle:
    def test_none_when_nothing_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert make_settings(tmp_path).resolved_ca_bundle() is None

    def test_blank_value_treated_as_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert make_settings(tmp_path, ca_bundle="  ").resolved_ca_bundle() is None

    def test_explicit_path_wins(self, tmp_path: Path) -> None:
        bundle = tmp_path / "corp-ca.pem"
        bundle.write_text("dummy pem", encoding="utf-8")
        settings = make_settings(tmp_path, ca_bundle=str(bundle))
        assert settings.resolved_ca_bundle() == bundle

    def test_explicit_missing_path_fails_fast(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, ca_bundle=str(tmp_path / "nope.pem"))
        with pytest.raises(FileNotFoundError, match="PHEONIX_CA_BUNDLE"):
            settings.resolved_ca_bundle()

    def test_certs_dir_autodetected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "certs").mkdir()
        (tmp_path / "certs" / "phoenix-ca.pem").write_text("dummy pem", encoding="utf-8")
        assert make_settings(tmp_path).resolved_ca_bundle() == Path("certs/phoenix-ca.pem")


class TestBuildTlsVerify:
    def test_defaults_to_none_meaning_stock_httpx(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert build_tls_verify(make_settings(tmp_path)) is None

    def test_verify_disabled_returns_false(self, tmp_path: Path) -> None:
        assert build_tls_verify(make_settings(tmp_path, tls_verify=False)) is False

    def test_ca_bundle_returns_ssl_context(self, tmp_path: Path) -> None:
        import ssl

        import certifi

        settings = make_settings(tmp_path, ca_bundle=certifi.where())
        context = build_tls_verify(settings)
        assert isinstance(context, ssl.SSLContext)
        assert len(context.get_ca_certs()) > 0


# ---------------------------------------------------------------------------
# scrape_once
# ---------------------------------------------------------------------------
class FakeWrapper:
    """Stands in for PhoenixClientWrapper: returns queued frames, records calls."""

    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self.frames = list(frames)
        self.calls: list[dict] = []

    def fetch_spans(self, project, start, end, limit) -> pd.DataFrame:
        self.calls.append({"project": project, "start": start, "end": end, "limit": limit})
        return self.frames.pop(0)


class TestScrapeOnce:
    def test_first_run_pulls_everything(self, tmp_store: Store, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        client = FakeWrapper([pd.DataFrame([flat_row(i) for i in range(5)])])

        report = scrape_once(tmp_store, client, settings)

        assert client.calls[0]["start"] is None
        assert client.calls[0]["project"] == PROJECT
        assert client.calls[0]["limit"] == settings.scrape_limit
        assert report.source == "live"
        assert report.pulled == 5
        assert report.inserted == 5
        assert report.skipped == 0
        assert report.watermark_before is None
        assert report.watermark_after == BASE_TS + timedelta(minutes=4)
        assert tmp_store.get_watermark(f"phoenix:{PROJECT}") == BASE_TS + timedelta(minutes=4)

    def test_second_run_uses_overlap_and_dedups(self, tmp_store: Store, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        first = pd.DataFrame([flat_row(i) for i in range(5)])
        second = pd.DataFrame([flat_row(i) for i in range(3, 8)])  # 3,4 overlap
        client = FakeWrapper([first, second])

        scrape_once(tmp_store, client, settings)
        report = scrape_once(tmp_store, client, settings)

        wm_after_first = BASE_TS + timedelta(minutes=4)
        expected_start = wm_after_first - timedelta(minutes=settings.scrape_overlap_minutes)
        assert client.calls[1]["start"] == expected_start
        assert report.watermark_before == wm_after_first
        assert report.pulled == 5
        assert report.inserted == 3  # overlapping span_ids not double-inserted
        assert report.skipped == 2
        assert report.watermark_after == BASE_TS + timedelta(minutes=7)
        assert len(tmp_store.spans_frame()) == 8

    def test_watermark_never_moves_backwards(self, tmp_store: Store, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        fresh = pd.DataFrame([flat_row(i) for i in range(5)])
        stale = pd.DataFrame([flat_row(i) for i in range(2)])  # only old spans re-pulled
        client = FakeWrapper([fresh, stale])

        scrape_once(tmp_store, client, settings)
        report = scrape_once(tmp_store, client, settings)

        watermark = BASE_TS + timedelta(minutes=4)
        assert report.watermark_after == watermark
        assert tmp_store.get_watermark(f"phoenix:{PROJECT}") == watermark

    def test_empty_pull_leaves_watermark_untouched(self, tmp_store: Store, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        client = FakeWrapper([pd.DataFrame()])

        report = scrape_once(tmp_store, client, settings)

        assert report.pulled == 0
        assert report.inserted == 0
        assert report.watermark_before is None
        assert report.watermark_after is None
        assert tmp_store.get_watermark(f"phoenix:{PROJECT}") is None

    def test_since_bounds_first_run(self, tmp_store: Store, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        client = FakeWrapper([pd.DataFrame([flat_row(0)])])
        since = BASE_TS - timedelta(days=7)

        scrape_once(tmp_store, client, settings, since=since)

        assert client.calls[0]["start"] == since

    def test_watermark_wins_over_since(self, tmp_store: Store, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        client = FakeWrapper([pd.DataFrame([flat_row(i) for i in range(3)]), pd.DataFrame()])

        scrape_once(tmp_store, client, settings)
        scrape_once(tmp_store, client, settings, since=BASE_TS - timedelta(days=30))

        watermark = BASE_TS + timedelta(minutes=2)
        expected_start = watermark - timedelta(minutes=settings.scrape_overlap_minutes)
        assert client.calls[1]["start"] == expected_start

    def test_rows_missing_span_id_are_skipped(self, tmp_store: Store, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        bad = flat_row(9, **{"context.span_id": None})
        client = FakeWrapper([pd.DataFrame([flat_row(0), bad])])

        report = scrape_once(tmp_store, client, settings)

        assert report.pulled == 2
        assert report.inserted == 1
        assert report.skipped == 1


# ---------------------------------------------------------------------------
# ingest_jsonl
# ---------------------------------------------------------------------------
class TestIngestJsonl:
    def test_end_to_end_from_file(self, tmp_store: Store, tmp_path: Path) -> None:
        lines = [
            json.dumps(nested_row(0)),
            json.dumps(flat_row(1)),
            "",  # blank lines ignored
            "{not valid json",  # malformed line skipped
            json.dumps({"name": "no-ids", "start_time": BASE_TS.isoformat()}),  # unmappable
            json.dumps(nested_row(2)),
        ]
        path = tmp_path / "spans.jsonl"
        path.write_text("\n".join(lines), encoding="utf-8")

        report = ingest_jsonl(tmp_store, path, PROJECT)

        assert report.source == "jsonl"
        assert report.pulled == 5  # non-blank lines
        assert report.inserted == 3
        assert report.skipped == 2
        frame = tmp_store.spans_frame()
        assert len(frame) == 3
        assert set(frame["project"]) == {PROJECT}
        assert set(frame["span_id"]) == {"px-span-0000", "px-span-0001", "px-span-0002"}

    def test_reingest_is_idempotent(self, tmp_store: Store, tmp_path: Path) -> None:
        path = tmp_path / "spans.jsonl"
        path.write_text(json.dumps(nested_row(0)) + "\n", encoding="utf-8")

        first = ingest_jsonl(tmp_store, path, PROJECT)
        second = ingest_jsonl(tmp_store, path, PROJECT)

        assert first.inserted == 1
        assert second.inserted == 0
        assert second.skipped == 1
        assert len(tmp_store.spans_frame()) == 1
