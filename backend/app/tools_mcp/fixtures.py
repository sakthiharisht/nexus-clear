"""FIXTURE-mode registry data (SPEC.md section 7.6): reads the same
`eval/fixtures/registry/{nppes,tx_license,leie}.json` files
app/eval/baseline_reconcile.py (M3) already reads, keyed by query
input (npi / license_number / name) - SPEC's own note says this
format is "a provisional preview... not a spec," free to change, but
it already carries everything the real tool adapters need, so there
is nothing to gain from reshaping it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_TOOLS = ("nppes", "tx_license", "leie")


def load_registry_fixtures(fixtures_root: Path) -> dict[str, dict[str, Any]]:
    fixtures: dict[str, dict[str, Any]] = {}
    for tool in _TOOLS:
        path = fixtures_root / f"{tool}.json"
        fixtures[tool] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return fixtures
