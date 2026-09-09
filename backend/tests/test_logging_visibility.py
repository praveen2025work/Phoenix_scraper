"""The scrape has to be legible from the logs: is Phoenix being called, and what came back.

Every one of these covers a case where the app previously did the right thing in
total silence, which is indistinguishable from doing nothing at all.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from phoenix_scraper.config import Settings
from phoenix_scraper.logging_setup import configure_logging
from phoenix_scraper.phoenix_client import PhoenixClientWrapper
from phoenix_scraper.scraper import scrape_once
from phoenix_scraper.storage import Store

BASE_TS = datetime(2026, 8, 7, 9, 0, 0, tzinfo=UTC)
PROJECT = "agent1-finance"


def make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "test.db", **kwargs)


def span_row(i: int) -> dict:
    return {
        "context.span_id": f"s{i:04d}",
        "context.trace_id": f"t{i:04d}",
        "name": "ChatCompletion",
        "start_time": (BASE_TS + timedelta(minutes=i)).isoformat(),
        "attributes.openinference.span.kind": "LLM",
        "attributes.input.value": "Why is there a break on the FX book?",
        "attributes.output.value": "Unsettled trade.",
    }


class FakeWrapper:
    def __init__(self, frames):
        self.frames = list(frames)
        self.calls: list[dict] = []

    def fetch_spans(self, project, start, end, limit) -> pd.DataFrame:
        self.calls.append({"project": project, "start": start, "end": end, "limit": limit})
        return self.frames.pop(0)


class TestScrapeLogging:
    def test_scrape_once_logs_a_one_line_summary(self, tmp_path: Path, caplog) -> None:
        settings = make_settings(tmp_path, project=PROJECT)
        client = FakeWrapper([pd.DataFrame([span_row(i) for i in range(3)])])

        with caplog.at_level(logging.INFO, logger="phoenix_scraper"), \
                Store(settings.db_path) as store:
            scrape_once(store, client, settings)

        summary = [r.getMessage() for r in caplog.records if "scrape" in r.getMessage()]
        assert summary, "a completed scrape must say what it pulled"
        assert PROJECT in summary[0]
        assert "pulled 3" in summary[0]
        assert "inserted 3" in summary[0]

    def test_offline_scrape_says_why_phoenix_was_skipped(self, tmp_path: Path) -> None:
        """"Not available" is useless on its own — no endpoint and no client library
        are different problems with different fixes."""
        no_endpoint = PhoenixClientWrapper(make_settings(tmp_path))

        reason = no_endpoint.unavailable_reason()

        assert reason is not None
        assert "PHOENIX_COLLECTOR_ENDPOINT" in reason

    def test_configured_client_reports_no_reason(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phoenix.example.com"
        )
        assert PhoenixClientWrapper(settings).unavailable_reason() is None


class TestConfigureLogging:
    @pytest.fixture(autouse=True)
    def _reset(self):
        names = ("phoenix_scraper", "httpx")
        saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).level)
                 for n in names}
        for n in names:
            logging.getLogger(n).handlers.clear()
        yield
        for n, (handlers, level) in saved.items():
            logger = logging.getLogger(n)
            logger.handlers.clear()
            logger.handlers.extend(handlers)
            logger.setLevel(level)

    def test_installs_a_handler_at_the_configured_level(self) -> None:
        configure_logging("DEBUG")
        pkg = logging.getLogger("phoenix_scraper")
        assert pkg.handlers
        assert pkg.level == logging.DEBUG

    def test_is_idempotent(self) -> None:
        """create_app and the CLI callback can both run in one process."""
        configure_logging("INFO")
        configure_logging("INFO")
        assert len(logging.getLogger("phoenix_scraper").handlers) == 1

    def test_unknown_level_falls_back_to_info(self) -> None:
        configure_logging("not-a-level")
        assert logging.getLogger("phoenix_scraper").level == logging.INFO

    def test_debug_also_surfaces_the_http_client(self) -> None:
        """At DEBUG the question is "did the request leave the box?" — only httpx
        can answer that, and it is silent under our package logger alone."""
        configure_logging("DEBUG")
        assert logging.getLogger("httpx").handlers

    def test_info_leaves_the_http_client_alone(self) -> None:
        configure_logging("INFO")
        assert not logging.getLogger("httpx").handlers


class TestLogLevelFromEnvFile:
    def test_pheonix_log_level_is_a_setting(self, tmp_path: Path, monkeypatch) -> None:
        """It has to come from Settings, not os.environ.

        pydantic-settings reads .env itself and never exports into the process
        environment, so an os.environ lookup silently ignores backend/.env.
        """
        env_file = tmp_path / ".env"
        env_file.write_text("PHEONIX_LOG_LEVEL=DEBUG\n", encoding="utf-8")

        settings = Settings(_env_file=env_file, db_path=tmp_path / "t.db")

        assert settings.log_level == "DEBUG"
        monkeypatch.delenv("PHEONIX_LOG_LEVEL", raising=False)
        import os

        assert os.environ.get("PHEONIX_LOG_LEVEL") is None  # .env never reaches here
