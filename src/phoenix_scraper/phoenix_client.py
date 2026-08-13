"""Phoenix connectivity — the ONLY module that talks to a live Phoenix server."""

import importlib.util
import logging
import ssl
import time
from datetime import datetime

import pandas as pd

from .config import Settings

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0
# Mirrors arize-phoenix-client's default timeout, which does not apply when we
# supply our own http_client.
_HTTP_TIMEOUT = {"connect": 10.0, "read": 30.0, "write": 10.0, "pool": 10.0}


def build_tls_verify(settings: Settings) -> ssl.SSLContext | bool | None:
    """TLS verification override for internal/corporate Phoenix endpoints.

    Returns None when stock httpx verification applies, False when verification
    is explicitly disabled (PHEONIX_TLS_VERIFY=false), or an SSLContext trusting
    both the standard bundle and the configured corporate CA.
    """
    if not settings.tls_verify:
        logger.warning(
            "TLS certificate verification is DISABLED (PHEONIX_TLS_VERIFY=false); "
            "only use this on a trusted internal network"
        )
        return False
    ca_bundle = settings.resolved_ca_bundle()
    if ca_bundle is None:
        return None

    import certifi

    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=str(ca_bundle))
    logger.info("Phoenix TLS verification trusts extra CA bundle %s", ca_bundle)
    return context


class PhoenixClientWrapper:
    """Thin wrapper around arize-phoenix-client (~=2.13) with retries and lazy import."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def available(self) -> bool:
        """True when an endpoint is configured AND arize-phoenix-client is importable."""
        if not self._settings.phoenix_endpoint:
            return False
        try:
            return importlib.util.find_spec("phoenix.client") is not None
        except (ImportError, ValueError):
            return False

    def fetch_spans(
        self,
        project: str,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> pd.DataFrame:
        endpoint = self._settings.phoenix_endpoint
        if not endpoint:
            raise RuntimeError(
                "Phoenix endpoint is not configured. Set PHOENIX_COLLECTOR_ENDPOINT "
                "(and PHOENIX_API_KEY if required) in the environment or .env file."
            )
        try:
            # Lazy import: the phoenix extra is optional at runtime.
            import httpx
            from phoenix.client import Client
            from phoenix.client.types.spans import SpanQuery
        except ImportError as exc:
            raise RuntimeError(
                "arize-phoenix-client is not installed. Install the phoenix extra, "
                "e.g. `uv sync --extra phoenix` or `pip install arize-phoenix-client`."
            ) from exc

        # The phoenix Client ignores base_url/api_key when http_client is given,
        # so the custom client must carry the base URL and auth header itself.
        http_client = None
        verify = build_tls_verify(self._settings)
        if verify is not None:
            headers = {}
            if self._settings.phoenix_api_key:
                headers["Authorization"] = f"Bearer {self._settings.phoenix_api_key}"
            http_client = httpx.Client(
                base_url=endpoint,
                headers=headers,
                verify=verify,
                timeout=httpx.Timeout(**_HTTP_TIMEOUT),
            )
        client = Client(
            base_url=endpoint,
            api_key=self._settings.phoenix_api_key,
            http_client=http_client,
        )
        retryable = (ConnectionError, TimeoutError, httpx.TransportError)
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return client.spans.get_spans_dataframe(
                    query=SpanQuery(),
                    start_time=start,
                    end_time=end,
                    limit=limit,
                    project_identifier=project,
                )
            except retryable as exc:
                last_error = exc
                if attempt < _MAX_ATTEMPTS:
                    delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "Phoenix fetch attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt, _MAX_ATTEMPTS, exc, delay,
                    )
                    time.sleep(delay)
        raise RuntimeError(
            f"Failed to fetch spans from Phoenix at {endpoint} after "
            f"{_MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error
