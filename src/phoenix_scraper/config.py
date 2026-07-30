"""Settings loaded from environment variables (see .env.example)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHEONIX_", env_file=".env", extra="ignore")

    # Phoenix connection (read directly from PHOENIX_* to match the official client)
    phoenix_endpoint: str | None = Field(default=None, alias="PHOENIX_COLLECTOR_ENDPOINT")
    phoenix_api_key: str | None = Field(default=None, alias="PHOENIX_API_KEY")

    # Inbound auth for OUR API (distinct from phoenix_api_key, which is outbound):
    # when set, every route except /health requires it via the X-API-Key header.
    api_key: str | None = None

    project: str = "default"
    db_path: Path = Path("data/pheonix.db")
    export_dir: Path = Path("data/exports")

    skills_catalog: Path = Path("config/skills_catalog.yaml")
    skills_dirs: str = ""  # comma-separated directories containing SKILL.md files
    pricing_path: Path = Path("config/pricing.yaml")

    # analysis knobs
    cluster_fuzz_threshold: int = 90  # rapidfuzz token_set_ratio 0-100
    skill_match_threshold: float = 0.55  # 0-1 combined match score
    scrape_overlap_minutes: int = 15  # watermark lookback to catch late-arriving spans
    scrape_limit: int = 5000

    def skills_dir_paths(self) -> list[Path]:
        return [Path(p.strip()) for p in self.skills_dirs.split(",") if p.strip()]


def load_settings() -> Settings:
    return Settings()
