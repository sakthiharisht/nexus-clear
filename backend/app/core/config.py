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

    # Extract (SPEC.md section 7.3) / Reconcile (section 7.5): Claude is
    # the only backend for both (M6/M7 - no Jev extraction, no Jev
    # same_person pre-filter per section 7.5's as-built note). Same
    # pinned-version discipline as model_classify_fallback.
    model_extract: str = "claude-haiku-5-5"
    model_investigate: str = "claude-haiku-5-5"

    # Gap report phrasing (SPEC.md section 7.8): Claude only phrases -
    # code verifies every sentence (app/report/gap_report.py) before
    # trusting it, same CLAUDE.md invariant 1 discipline as every
    # other stage.
    model_report: str = "claude-haiku-5-5"

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

    # GET /eval/latest (app/api/eval_endpoint.py) - same local-checkout
    # default as model_cache_root/registry_fixtures_root above, same
    # need to override it in Docker (docker-compose.yml).
    eval_runs_dir: Path = _REPO_ROOT / "eval" / "runs"

    # Reconcile (SPEC.md section 7.5): hard cap on tool calls per
    # Investigator invocation - Jev is "known to repeat tool calls in
    # agent loops" per SPEC 7.2, and an unbounded Claude loop is the
    # same risk with a different model. Tuned from the eval, not
    # load-bearing enough yet to need its own config section.
    investigator_max_tool_calls: int = 6

    # Escalate (SPEC.md section 7.7). Any finding with a resolved
    # confidence below `low_confidence_threshold` goes to review
    # regardless of severity; `blocker_confidence_threshold` is the
    # severity override - a blocker stays in review up to a higher bar
    # (0.60-0.90 is "shown to provider with a caveat" for anything
    # else, but never for a blocker). Tune from the eval calibration
    # curve, same as classify's tau_classify/legible_threshold.
    low_confidence_threshold: float = 0.60
    blocker_confidence_threshold: float = 0.90

    # Pre-M9 fix #4 - demo-grade auth (SPEC.md section 8: "a role
    # switch (provider | reviewer), no real auth in MVP"). One shared
    # secret for the reviewer role across every case - unlike
    # provider_token (per-case, app/core/orm.py's Case.provider_token),
    # there's exactly one reviewer role in this demo, not one per
    # case. Never a real identity/authorization system; README (M9)
    # states this plainly.
    reviewer_token: str = "demo-reviewer-token"


settings = Settings()
