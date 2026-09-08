"""TLS/connectivity diagnostics behind `pheonix doctor`.

Everything here is read-only and uses only the standard library (plus httpx for
the live probe, which is skipped when it is not installed).
"""

import importlib.util
import os
import re
import ssl
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

Probe = Callable[[Settings], tuple[bool, str]]

_CERT_HINTS = (
    "Hints:",
    "  - 'self-signed certificate in certificate chain' means the corporate root",
    "    is not trusted yet: put it at certs/phoenix-ca.pem (README, 'HTTPS",
    "    endpoint' section).",
    "  - No self-signed root in your bundle? Re-extract the full chain:",
    "    openssl s_client -showcerts -connect <host>:443 </dev/null | \\",
    "      awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/' > certs/phoenix-ca.pem",
    "  - Last resort on a trusted internal network: PHEONIX_TLS_VERIFY=false in .env.",
)
_NETWORK_HINTS = (
    "Hints:",
    "  - The failure does not look TLS-related: check VPN, DNS, host and port,",
    "    and that the endpoint opens from a browser on this machine.",
)
_TLS_KEYWORDS = ("certificate", "ssl", "tls", "handshake", "bundle")
_USERINFO_RE = re.compile(r"//[^/@\s]+@")


def _redact(text: str) -> str:
    """Strip user:password@ userinfo from any URL embedded in the text."""
    return _USERINFO_RE.sub("//", text)


def _failure_hints(message: str) -> tuple[str, ...]:
    if message.startswith("probe skipped"):
        return ()
    lowered = message.lower()
    if any(keyword in lowered for keyword in _TLS_KEYWORDS):
        return _CERT_HINTS
    return _NETWORK_HINTS


@dataclass(frozen=True)
class CertInfo:
    subject: str
    issuer: str
    not_after: str
    is_root: bool  # self-signed: subject == issuer


@dataclass(frozen=True)
class BundleInfo:
    n_pem_blocks: int
    certs: tuple[CertInfo, ...]
    error: str | None

    @property
    def has_root(self) -> bool:
        return any(cert.is_root for cert in self.certs)


def describe_ca_bundle(path: Path) -> BundleInfo:
    """Parse a PEM bundle with the stdlib ssl module (no extra dependencies)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return BundleInfo(n_pem_blocks=0, certs=(), error=str(exc))
    n_blocks = text.count("-----BEGIN CERTIFICATE-----")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        context.load_verify_locations(cafile=str(path))
    except ssl.SSLError as exc:
        return BundleInfo(n_pem_blocks=n_blocks, certs=(), error=str(exc))

    certs = []
    for raw in context.get_ca_certs():
        subject = _x509_name(raw.get("subject", ()))
        issuer = _x509_name(raw.get("issuer", ()))
        certs.append(
            CertInfo(
                subject=subject,
                issuer=issuer,
                not_after=str(raw.get("notAfter", "?")),
                is_root=subject == issuer,
            )
        )
    return BundleInfo(n_pem_blocks=n_blocks, certs=tuple(certs), error=None)


def _x509_name(rdns: tuple) -> str:
    """Flatten ssl's ((('commonName', 'X'),), ...) RDN structure to one string."""
    return ", ".join(f"{key}={value}" for rdn in rdns for key, value in rdn)


def tls_probe(settings: Settings) -> tuple[bool, str]:
    """GET the endpoint with the exact TLS settings the scraper would use.

    Any HTTP status counts as success: it proves the TLS handshake worked.
    """
    try:
        import httpx
    except ImportError:
        return False, "probe skipped: httpx is not installed (pip install -r requirements-live.txt)"

    from .phoenix_client import build_tls_verify

    endpoint = settings.phoenix_endpoint or ""
    try:
        verify = build_tls_verify(settings)
    except (FileNotFoundError, ssl.SSLError) as exc:
        return False, f"CA bundle could not be loaded: {exc}"
    kwargs: dict[str, object] = {} if verify is None else {"verify": verify}
    try:
        response = httpx.get(endpoint, timeout=10.0, follow_redirects=False, **kwargs)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return False, _redact(f"{type(exc).__name__}: {exc}")
    if verify is False:
        note = "connected WITHOUT certificate verification (PHEONIX_TLS_VERIFY=false)"
    elif endpoint.startswith("https"):
        note = "TLS handshake OK"
    else:
        note = "plain HTTP (no TLS involved)"
    message = f"{note} — HTTP {response.status_code}"
    if response.status_code in (401, 403):
        message += " (TLS is fine; authentication failed — check PHOENIX_API_KEY)"
    return True, message


_MAX_CERTS_LISTED = 10


def bundle_lines(path: Path, info: BundleInfo, source: str = "") -> list[str]:
    """Human-readable description of one CA bundle."""
    lines = [f"CA bundle:        {path}{source} ({info.n_pem_blocks} PEM block(s))"]
    if info.error:
        lines.append(f"  ERROR reading bundle: {info.error}")
        return lines
    now = time.time()
    for cert in info.certs[:_MAX_CERTS_LISTED]:
        role = "ROOT (self-signed)" if cert.is_root else "intermediate CA"
        expired = ""
        try:
            if ssl.cert_time_to_seconds(cert.not_after) < now:
                expired = "  [EXPIRED]"
        except ValueError:
            pass
        lines.append(f"  - [{role}] subject: {cert.subject}")
        lines.append(f"      issuer: {cert.issuer}  expires: {cert.not_after}{expired}")
    if len(info.certs) > _MAX_CERTS_LISTED:
        lines.append(f"  … and {len(info.certs) - _MAX_CERTS_LISTED} more")
    # get_ca_certs() only lists CA certs (basicConstraints CA:TRUE); anything
    # else in the file (e.g. a self-signed *server* cert) loads but stays unseen.
    unlisted = max(0, info.n_pem_blocks - len(info.certs))
    if unlisted:
        lines.append(
            f"  {unlisted} certificate(s) loaded but not listed — the stdlib only lists "
            "CA certificates; end-entity (leaf/server) certs are still trusted"
        )
    if not info.has_root:
        if unlisted:
            lines.append(
                "  note: no CA root among the listed certs, but unlisted certificates "
                "may still anchor trust — go by the connection probe result"
            )
        else:
            lines.append(
                "  WARNING: no self-signed root found in the bundle — this is usually why "
                "verification still fails. Re-extract the full chain (README, 'HTTPS "
                "endpoint' section)."
            )
    return lines


def doctor_report(settings: Settings, probe: Probe = tls_probe) -> list[str]:
    """Assemble the `pheonix doctor` output as plain lines (easy to test)."""
    endpoint = settings.phoenix_endpoint
    client_installed = importlib.util.find_spec("phoenix.client") is not None
    client_line = (
        "installed" if client_installed else "NOT installed (pip install -r requirements-live.txt)"
    )

    endpoint_line = (
        _redact(endpoint) if endpoint else "(not set — fill PHOENIX_COLLECTOR_ENDPOINT in .env)"
    )
    lines = [
        f"python:           {sys.version.split()[0]} ({sys.executable})",
        f"working dir:      {Path.cwd()}",
        f"endpoint:         {endpoint_line}",
        f"project:          {settings.project}",
        f"phoenix client:   {client_line}",
    ]

    if not settings.tls_verify:
        lines.append("tls verification: DISABLED (PHEONIX_TLS_VERIFY=false) — cert checks are off")
    else:
        try:
            bundle = settings.resolved_ca_bundle()
        except FileNotFoundError as exc:
            lines.append(f"CA bundle:        MISSING — {exc}")
            bundle = None
        else:
            if bundle is not None:
                lines.extend(bundle_lines(bundle, describe_ca_bundle(bundle)))
            elif ssl_cert_file := os.environ.get("SSL_CERT_FILE"):
                # httpx honors SSL_CERT_FILE when we don't override verify.
                shell_bundle = Path(ssl_cert_file)
                lines.extend(
                    bundle_lines(
                        shell_bundle,
                        describe_ca_bundle(shell_bundle),
                        source=" (from shell SSL_CERT_FILE)",
                    )
                )
            else:
                lines.append(
                    "CA bundle:        none — stock verification (drop your corporate root CA "
                    "at certs/phoenix-ca.pem to trust it)"
                )

    if endpoint:
        ok, message = probe(settings)
        lines.append(f"connection probe: {'OK' if ok else 'FAILED'} — {_redact(message)}")
        if not ok:
            lines.extend(_failure_hints(message))
    else:
        lines.append("connection probe: skipped (no endpoint configured)")
    return lines
