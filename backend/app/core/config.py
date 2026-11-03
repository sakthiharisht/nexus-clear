"""Application settings, loaded from environment variables / .env.

Settings for later milestones (model routing, tool modes, escalation
thresholds — see SPEC.md section 12) are added when the milestone that
needs them lands, not speculatively.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/nexus_clear"

    # Vault (SPEC.md section 7.1 / section 12's MASTER_KEY_PATH). Both
    # default under the gitignored data/ directory — never committed
    # (CLAUDE.md invariant 4).
    master_key_path: Path = Path("data/vault/master.key")
    blob_store_root: Path = Path("data/vault/blobs")

    # Intake upload limits (SPEC.md section 7.1: "Accept PDF/PNG/JPG, size
    # cap, magic-byte check").
    max_upload_size_bytes: int = 15 * 1024 * 1024  # 15 MB


settings = Settings()
