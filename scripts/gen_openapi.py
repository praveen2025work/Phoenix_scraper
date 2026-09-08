"""Write the FastAPI OpenAPI schema to a file (for openapi-typescript)."""

import json
import sys
from pathlib import Path

from phoenix_scraper.api import create_app
from phoenix_scraper.config import load_settings

out = Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/openapi.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps(create_app(load_settings()).openapi(), indent=2) + "\n", encoding="utf-8"
)
print(f"wrote {out}")
