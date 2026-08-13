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

    # Skill coverage: a cluster matched to a skill counts as ALREADY COVERED when
    # it resembles one of that skill's own example_prompts (or its description)
    # this closely. Below it, the skill owns the question by keyword but shows no
    # example of it — the gap `pheonix coverage` reports.
    skill_coverage_threshold: float = 0.70  # 0-1 fuzzy similarity
    max_suggested_prompts: int = 8  # example_prompts proposed per skill per run
    run_history_limit: int = 20  # analysis runs kept for run-over-run diffing

    # validation knobs (see evaluations.py). Defaults are deliberately lenient:
    # a code check that cries wolf gets ignored, and then nothing gets validated.
    evaluate_on_analyze: bool = True  # run the CODE checks as part of `analyze`
    # Share of the question's content terms an answer must echo for full credit.
    # Deliberately low: lexical overlap is a weak signal that only reliably
    # catches answers sharing almost nothing with the question. Raising it makes
    # the check fire on perfectly good short answers.
    eval_relevance_overlap: float = 0.15
    eval_repetition_threshold: float = 0.35  # min distinct-word ratio before "repetitive"
    eval_outlier_quantile: float = 0.95  # latency / prompt-length outlier cut
    eval_outlier_factor: float = 2.0  # ... and it must also exceed factor x median
    annotation_batch_size: int = 100  # span_ids per Phoenix annotation request
    scrape_overlap_minutes: int = 15  # watermark lookback to catch late-arriving spans
    scrape_limit: int = 5000
    # Read timeout (seconds) for Phoenix API calls. The first scrape scans the
    # project's full history and can exceed the 30s default on large projects.
    http_timeout: float = 30.0

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
