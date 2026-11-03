"""Application settings, loaded from environment variables / .env.

Only M0-era settings live here. Settings for later milestones (model routing,
tool modes, escalation thresholds — see SPEC.md section 12) are added when the
milestone that needs them lands, not speculatively.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/nexus_clear"


settings = Settings()
