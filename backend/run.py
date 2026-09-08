#!/usr/bin/env python3
"""Run the pheonix backend — API + background job worker — on http://localhost:8000.

    cd backend
    pip install -r requirements.txt
    python run.py

Options:
    python run.py --host 0.0.0.0 --port 9000 --reload
"""

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
SRC = BACKEND / "src"

# .env, data/, config/, certs/ are all resolved relative to the working directory.
os.chdir(BACKEND)
sys.path.insert(0, str(SRC))
os.environ["PYTHONPATH"] = str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="auto-reload on code change (dev)")
    args = ap.parse_args()

    try:
        import uvicorn
    except ModuleNotFoundError:
        sys.exit("Dependencies missing — run:  pip install -r requirements.txt")

    print(f"pheonix API + job worker  ->  http://{args.host}:{args.port}   (API docs: /docs)")
    uvicorn.run(
        "phoenix_scraper.api:create_app_default",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(SRC)] if args.reload else None,
    )


if __name__ == "__main__":
    main()
