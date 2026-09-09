"""One place that decides where this package's logs go.

The CLI and the API each need it, and both may run in the same process, so it has
to be idempotent — without that, `pheonix serve` would print every line twice.
"""

import logging

_PACKAGE = "phoenix_scraper"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# Only at DEBUG: httpx logs one line per request ("HTTP Request: POST ... 200 OK"),
# which is the only direct evidence that a call actually left the machine.
_HTTP_LOGGER = "httpx"


def _attach(name: str, level: int) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Attach a stderr handler to the `phoenix_scraper` logger at `level`.

    At DEBUG the http client is wired up too, so "is it pulling?" can be answered
    from the wire rather than inferred from our own log lines.

    An unrecognised level falls back to INFO rather than raising: a typo in
    PHEONIX_LOG_LEVEL should not stop the server from starting.
    """
    resolved = getattr(logging, str(level).upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    if resolved <= logging.DEBUG:
        _attach(_HTTP_LOGGER, resolved)
    return _attach(_PACKAGE, resolved)
