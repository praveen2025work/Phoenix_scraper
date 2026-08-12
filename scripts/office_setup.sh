#!/usr/bin/env bash
# One-shot office bootstrap: venv + pinned deps + pheonix CLI + offline verification.
# No uv required — plain python + pip only.
#
# Usage:
#   ./scripts/office_setup.sh          # offline analysis only
#   ./scripts/office_setup.sh --live   # also install the Phoenix client for live scraping
#
# Corporate proxy / mirror: export these BEFORE running (see README step 2):
#   PIP_INDEX_URL, SSL_CERT_FILE, REQUESTS_CA_BUNDLE
set -euo pipefail

cd "$(dirname "$0")/.."

REQS=requirements.txt
case "${1:-}" in
  "") ;;
  --live) REQS=requirements-live.txt ;;
  *)
    echo "ERROR: unknown argument: $1 (only --live is supported)" >&2
    exit 2
    ;;
esac

version_ok() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

find_python() {
  local cand
  for cand in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && version_ok "$cand"; then
      command -v "$cand"
      return 0
    fi
  done
  return 1
}

PYTHON=$(find_python) || {
  echo "ERROR: no Python 3.11+ found on PATH (tried python3.14/3.13/3.12/3.11/python3/python)." >&2
  echo "Install Python 3.11+ (software portal / IT), then re-run." >&2
  exit 1
}
echo "Using $PYTHON ($("$PYTHON" --version 2>&1))"

# Reuse .venv only if it holds a working 3.11+ interpreter WITH pip.
# uv-created venvs ship without pip, so bootstrap or rebuild as needed.
if [[ -d .venv ]]; then
  if ! version_ok .venv/bin/python; then
    echo "Existing .venv has no usable Python 3.11+ — recreating it."
    "$PYTHON" -m venv --clear .venv
  elif ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    echo "Existing .venv has no pip (created by uv?) — bootstrapping it with ensurepip."
    .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || {
      echo "ensurepip failed — recreating .venv from scratch."
      "$PYTHON" -m venv --clear .venv
    }
  fi
else
  "$PYTHON" -m venv .venv
fi

.venv/bin/python -m pip install -r "$REQS"
.venv/bin/python -m pip install -e . --no-deps

echo
echo "Verifying the offline pipeline (no Phoenix connection needed)..."
.venv/bin/pheonix demo

cat <<'EOF'

Setup complete. To scrape your live Phoenix instance:
  1. cp .env.example .env
  2. set PHOENIX_COLLECTOR_ENDPOINT (+ PHOENIX_API_KEY if your Phoenix has auth,
     and PHEONIX_PROJECT if your traces are not in "default")
  3. .venv/bin/pheonix scrape && .venv/bin/pheonix analyze && .venv/bin/pheonix report

Activate the venv for interactive use: source .venv/bin/activate
EOF
