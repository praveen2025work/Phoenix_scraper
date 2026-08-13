"""Settings loaded from environment variables (see .env.example)."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Conventional drop-in location for a corporate root CA, relative to the cwd.
DEFAULT_CA_BUNDLE = Path("certs/phoenix-ca.pem")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHEONIX_", env_file=".env", extra="ignore")

    # Phoenix connection (read directly from PHOENIX_* to match the official client)
    phoenix_endpoint: str | None = Field(default=None, alias="PHOENIX_COLLECTOR_ENDPOINT")
    phoenix_api_key: str | None = Field(default=None, alias="PHOENIX_API_KEY")

    # TLS to Phoenix: corporate root CA in PEM format. Explicit path wins;
    # otherwise certs/phoenix-ca.pem is picked up automatically when present.
    ca_bundle: str = ""
    tls_verify: bool = True  # PHEONIX_TLS_VERIFY=false disables verification (last resort)

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

    @field_validator("phoenix_endpoint", "phoenix_api_key", "api_key", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """Blank values in .env (e.g. `PHOENIX_API_KEY=`) mean unset, not empty."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def skills_dir_paths(self) -> list[Path]:
        return [Path(p.strip()) for p in self.skills_dirs.split(",") if p.strip()]

    def resolved_ca_bundle(self) -> Path | None:
        """CA bundle to trust for the Phoenix connection, or None for stock httpx."""
        if self.ca_bundle.strip():
            path = Path(self.ca_bundle.strip())
            if not path.is_file():
                raise FileNotFoundError(
                    f"PHEONIX_CA_BUNDLE points to a missing file: {path}"
                )
            return path
        if DEFAULT_CA_BUNDLE.is_file():
            return DEFAULT_CA_BUNDLE
        return None


def load_settings() -> Settings:
    return Settings()
