"""Eval dashboard API (SPEC.md section 8: `GET /eval/latest`). Reads
the most recent `uv run python -m app.eval.run` output
(eval/runs/run-*.json, gitignored - regenerated locally, never
committed) - this endpoint does not run the eval itself, only serves
whatever was last written there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/eval", tags=["eval"])

# backend/app/api/eval_endpoint.py -> repo root, same convention as
# app/core/config.py's _REPO_ROOT.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNS_DIR = _REPO_ROOT / "eval" / "runs"


@router.get("/latest")
def get_latest_eval_run() -> dict[str, Any]:
    if not _RUNS_DIR.is_dir():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no eval runs found - run `uv run python -m app.eval.run` from the repo root first",
        )
    run_files = sorted(_RUNS_DIR.glob("run-*.json"))
    if not run_files:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no eval runs found - run `uv run python -m app.eval.run` from the repo root first",
        )
    latest: dict[str, Any] = json.loads(run_files[-1].read_text(encoding="utf-8"))
    return latest
