"""One place that decides where this package's logs go.

The CLI and the API each need it, and both may run in the same process, so it has
to be idempotent — without that, `pheonix serve` would print every line twice.
"""

import logging

_PACKAGE = "phoenix_scraper"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Attach a stderr handler to the `phoenix_scraper` logger at `level`.

    An unrecognised level falls back to INFO rather than raising: a typo in
    PHEONIX_LOG_LEVEL should not stop the server from starting.
    """
    resolved = getattr(logging, str(level).upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    package_logger = logging.getLogger(_PACKAGE)
    if not package_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        package_logger.addHandler(handler)
    package_logger.setLevel(resolved)
    return package_logger
