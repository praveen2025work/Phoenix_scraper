"""Tests for diagnostics (the `pheonix doctor` command)."""

from pathlib import Path

import certifi
import pytest

from phoenix_scraper import diagnostics
from phoenix_scraper.config import Settings


def make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "test.db", **kwargs)


def report_text(settings: Settings, **kwargs) -> str:
    return "\n".join(diagnostics.doctor_report(settings, **kwargs))


@pytest.fixture(autouse=True)
def _clean_phoenix_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_API_KEY", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)


class TestDescribeCaBundle:
    def test_parses_pem_blocks_and_roots(self) -> None:
        info = diagnostics.describe_ca_bundle(Path(certifi.where()))
        assert info.n_pem_blocks > 100
        assert len(info.certs) == info.n_pem_blocks
        assert info.has_root  # certifi's bundle is all self-signed roots
        first = info.certs[0]
        assert first.subject
        assert first.issuer
        assert first.is_root == (first.subject == first.issuer)

    def test_garbage_file_reports_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "junk.pem"
        bad.write_text("this is not a certificate", encoding="utf-8")
        info = diagnostics.describe_ca_bundle(bad)
        assert info.n_pem_blocks == 0
        assert info.error is not None


class TestDoctorReport:
    def test_reports_missing_endpoint(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        text = report_text(make_settings(tmp_path))
        assert "not set" in text

    def test_reports_endpoint_and_bundle(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path,
            PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal",
            ca_bundle=certifi.where(),
        )
        text = report_text(settings, probe=lambda s: (True, "TLS handshake OK (HTTP 200)"))
        assert "https://phx.internal" in text
        assert certifi.where() in text
        assert "root" in text.lower()
        assert "TLS handshake OK" in text

    def test_reports_no_bundle_as_stock_verification(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)  # no certs/ dir here
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal")
        text = report_text(settings, probe=lambda s: (False, "certificate verify failed"))
        assert "stock" in text.lower() or "none" in text.lower()
        assert "certificate verify failed" in text

    def test_missing_explicit_bundle_is_reported_not_raised(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path,
            PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal",
            ca_bundle=str(tmp_path / "nope.pem"),
        )
        text = report_text(settings, probe=lambda s: (False, "unreachable"))
        assert "missing" in text.lower()

    def test_warns_when_verification_disabled(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal", tls_verify=False
        )
        text = report_text(settings, probe=lambda s: (True, "connected (verification off)"))
        assert "DISABLED" in text

    def test_no_probe_without_endpoint(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        calls: list[Settings] = []

        def probe(settings: Settings):
            calls.append(settings)
            return True, "should not run"

        report_text(make_settings(tmp_path), probe=probe)
        assert calls == []

    def test_endpoint_credentials_are_redacted(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://svc-user:sekret-token@phx.internal"
        )
        text = report_text(settings, probe=lambda s: (False, "certificate verify failed"))
        assert "sekret-token" not in text
        assert "phx.internal" in text

    def test_cert_failure_gets_cert_hints(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal")
        text = report_text(settings, probe=lambda s: (False, "certificate verify failed"))
        assert "openssl s_client" in text

    def test_network_failure_gets_network_hints_not_cert_hints(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal")
        text = report_text(settings, probe=lambda s: (False, "ConnectError: connection refused"))
        assert "VPN" in text
        assert "openssl s_client" not in text

    def test_skipped_probe_gets_no_hints(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal")
        text = report_text(
            settings, probe=lambda s: (False, "probe skipped: httpx is not installed")
        )
        assert "Hints:" not in text

    def test_shell_ssl_cert_file_is_reported(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)  # no certs/ dir → PHEONIX bundle is None
        monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal")
        text = report_text(settings, probe=lambda s: (True, "TLS handshake OK — HTTP 200"))
        assert "SSL_CERT_FILE" in text
        assert certifi.where() in text

    def test_missing_root_gets_a_hint(self, tmp_path: Path) -> None:
        # A bundle whose only cert is not self-signed (fake by monkeypatching the
        # describe step is overkill: craft via describe_ca_bundle contract instead).
        info = diagnostics.BundleInfo(
            n_pem_blocks=1,
            certs=(
                diagnostics.CertInfo(
                    subject="commonName=leaf.internal",
                    issuer="commonName=Corp Issuing CA",
                    not_after="Jan  1 00:00:00 2030 GMT",
                    is_root=False,
                ),
            ),
            error=None,
        )
        lines = diagnostics.bundle_lines(Path("certs/phoenix-ca.pem"), info)
        text = "\n".join(lines)
        assert "no self-signed root" in text.lower()


class TestBundleLines:
    def test_unlisted_certs_are_explained_and_root_warning_softened(self) -> None:
        # stdlib get_ca_certs() omits CA:FALSE certs (e.g. a self-signed server
        # cert): 1 PEM block loaded, 0 listed. Must not claim the bundle is bad.
        info = diagnostics.BundleInfo(n_pem_blocks=1, certs=(), error=None)
        text = "\n".join(diagnostics.bundle_lines(Path("certs/phoenix-ca.pem"), info))
        assert "not listed" in text
        assert "WARNING" not in text
        assert "probe" in text  # points the user at the probe verdict instead

    def test_expired_cert_is_flagged(self) -> None:
        info = diagnostics.BundleInfo(
            n_pem_blocks=1,
            certs=(
                diagnostics.CertInfo(
                    subject="commonName=Old Corp Root CA",
                    issuer="commonName=Old Corp Root CA",
                    not_after="Jan  1 00:00:00 2021 GMT",
                    is_root=True,
                ),
            ),
            error=None,
        )
        text = "\n".join(diagnostics.bundle_lines(Path("x.pem"), info))
        assert "EXPIRED" in text


class TestTlsProbe:
    def test_unloadable_bundle_reports_not_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "garbage.pem"
        bad.write_text("not a certificate", encoding="utf-8")
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal", ca_bundle=str(bad)
        )
        ok, message = diagnostics.tls_probe(settings)
        assert ok is False
        assert "CA bundle could not be loaded" in message

    def test_malformed_endpoint_reports_not_raises(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal:notaport"
        )
        ok, message = diagnostics.tls_probe(settings)
        assert ok is False
        assert "InvalidURL" in message or "port" in message.lower()

    def test_success_wording_notes_disabled_verification(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(
            "httpx.get", lambda url, **kw: SimpleNamespace(status_code=200, url=url)
        )
        settings = make_settings(
            tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal", tls_verify=False
        )
        ok, message = diagnostics.tls_probe(settings)
        assert ok is True
        assert "WITHOUT certificate verification" in message
        assert "TLS handshake OK" not in message

    def test_auth_failure_noted_on_401(self, tmp_path: Path, monkeypatch) -> None:
        from types import SimpleNamespace

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "httpx.get", lambda url, **kw: SimpleNamespace(status_code=401, url=url)
        )
        settings = make_settings(tmp_path, PHOENIX_COLLECTOR_ENDPOINT="https://phx.internal")
        ok, message = diagnostics.tls_probe(settings)
        assert ok is True
        assert "authentication" in message.lower()


class TestDoctorCli:
    def test_invalid_env_degrades_to_message(self, monkeypatch, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        import phoenix_scraper.cli as cli_mod

        def broken_settings() -> Settings:
            return Settings(_env_file=None, tls_verify="maybe")  # type: ignore[arg-type]

        monkeypatch.setattr(cli_mod, "load_settings", broken_settings)
        result = CliRunner().invoke(cli_mod.app, ["doctor"])
        assert result.exit_code == 1
        assert "ValidationError" not in (result.output or "")
