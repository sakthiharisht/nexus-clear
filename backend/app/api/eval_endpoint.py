"""Eval dashboard API (SPEC.md section 8: `GET /eval/latest`). Reads
the most recent `uv run python -m app.eval.run` output
(eval/runs/run-*.json, gitignored - regenerated locally, never
committed) - this endpoint does not run the eval itself, only serves
whatever was last written there.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/latest")
def get_latest_eval_run() -> dict[str, Any]:
    runs_dir = settings.eval_runs_dir
    if not runs_dir.is_dir():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no eval runs found - run `uv run python -m app.eval.run` from the repo root first",
        )
    run_files = sorted(runs_dir.glob("run-*.json"))
    if not run_files:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no eval runs found - run `uv run python -m app.eval.run` from the repo root first",
        )
    latest: dict[str, Any] = json.loads(run_files[-1].read_text(encoding="utf-8"))
    return latest
