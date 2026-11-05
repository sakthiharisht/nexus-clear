"""Exports the FastAPI app's OpenAPI schema to frontend/openapi.json -
the frontend's `npm run gen:api` (openapi-typescript) reads this
static file, so generating types never needs a live backend running
(SPEC.md section 8: "OpenAPI is the contract; generate TS types with
openapi-typescript").
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    output_path = repo_root / "frontend" / "openapi.json"
    output_path.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output_path}")


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    main()
