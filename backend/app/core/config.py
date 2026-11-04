"""Application settings, loaded from environment variables / .env.

Settings for later milestones (model routing, tool modes, escalation
thresholds — see SPEC.md section 12) are added when the milestone that
needs them lands, not speculatively.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root. Absolute (unlike the vault
# paths below) because it must reach outside backend/ into /rules
# regardless of the process's working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/nexus_clear"

    rule_pack_path: Path = _REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"

    # Vault (SPEC.md section 7.1 / section 12's MASTER_KEY_PATH). Both
    # default under the gitignored data/ directory — never committed
    # (CLAUDE.md invariant 4). Relative (unlike rule_pack_path above): the
    # app always runs with backend/ as its working directory (uv run from
    # backend/, or the container's WORKDIR), so these resolve there.
    #
    # master_key is the production path: a base64-encoded 256-bit key
    # from a real secret store (env var injected by whatever manages
    # secrets - Docker/K8s secret, Vault, Parameter Store - never
    # typed in by hand). When unset, LocalKeyManager falls back to
    # master_key_path - see README.md's key-management caveat.
    master_key: str | None = None
    master_key_path: Path = Path("data/vault/master.key")
    blob_store_root: Path = Path("data/vault/blobs")

    # Intake upload limits (SPEC.md section 7.1: "Accept PDF/PNG/JPG, size
    # cap, magic-byte check").
    max_upload_size_bytes: int = 15 * 1024 * 1024  # 15 MB

    # Classify (SPEC.md section 7.2 / 12). ANTHROPIC_API_KEY is read
    # directly by the anthropic SDK, not duplicated here. JEV_MODEL is
    # the full versioned id ("jev-1.14.0"), never an alias like
    # "jev-latest" - CLAUDE.md invariant 7 / SPEC risk #1.
    decision_backend: Literal["jev", "claude"] = "claude"
    jev_api_key: str | None = None
    jev_model: str = "jev-1.14.0"
    model_classify_fallback: str = "claude-haiku-5-5"
    tau_classify: float = 0.85
    legible_threshold: float = 0.7

    # Record/replay cache for model calls (CLAUDE.md: "LLM/Jev calls go
    # through the record/replay cache so CI is offline and
    # deterministic. Live runs refresh the cache."). "replay" (the CI/
    # test default) never makes a network call - a cache miss is an
    # error, not a silent live fallback. "record" calls live and writes
    # the result to the cache for next time.
    model_cache_mode: Literal["replay", "record"] = "replay"
    model_cache_root: Path = _REPO_ROOT / "eval" / "fixtures" / "model_cache"

    # MCP tools (SPEC.md section 7.6). FIXTURE is the default and the
    # only mode tx_license_lookup ever runs in (BHEC has no verified
    # programmatic access - app/tools_mcp/server.py). "live" switches
    # nppes_lookup/leie_check to the real public NPPES API / LEIE CSV
    # download; synthetic providers won't exist there, so live mode is
    # a not-found/indeterminate demonstration, not the eval path.
    mcp_tool_mode: Literal["fixture", "live"] = "fixture"
    registry_fixtures_root: Path = _REPO_ROOT / "eval" / "fixtures" / "registry"
    leie_cache_path: Path = Path("data/cache/leie_updated.csv")

    # Reconcile (SPEC.md section 7.5): hard cap on tool calls per
    # Investigator invocation - Jev is "known to repeat tool calls in
    # agent loops" per SPEC 7.2, and an unbounded Claude loop is the
    # same risk with a different model. Tuned from the eval, not
    # load-bearing enough yet to need its own config section.
    investigator_max_tool_calls: int = 6


settings = Settings()
