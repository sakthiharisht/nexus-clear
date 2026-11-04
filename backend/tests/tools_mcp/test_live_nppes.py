"""Contract tests for LiveNppesAdapter against recorded sample response
shapes (SPEC.md section 7.6: "LIVE adapters get contract tests against
recorded sample response shapes") - no real network call, so these run
offline in CI. The "not found" shape below is the REAL response this
project captured live on 2026-11-04 (see live_nppes.py's module
docstring); the "found" shape is a structurally identical sample built
from a synthetic name - the real person's data that confirmed this
shape during verification is never committed (CLAUDE.md invariant 4).

One opt-in test at the bottom makes a real call against an obviously
fake NPI, gated behind RUN_LIVE_REGISTRY_TESTS - skipped by default
(including in CI), matching this project's established opt-in-live
pattern (tests/backends/test_live_smoke.py) even though this adapter
needs no API key.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from app.tools_mcp.live_nppes import LiveNppesAdapter

_NOT_FOUND_RESPONSE = {"result_count": 0, "results": []}

_FOUND_RESPONSE = {
    "result_count": 1,
    "results": [
        {
            "number": "1000000004",
            "enumeration_type": "NPI-1",
            "basic": {
                "first_name": "SAMPLE",
                "last_name": "PROVIDER",
                "status": "A",
            },
            "taxonomies": [
                {"desc": "Counselor, Professional", "primary": True, "state": "TX"},
                {"desc": "Psychiatric Unit", "primary": False, "state": "TX"},
            ],
            "addresses": [],
        }
    ],
}


def _adapter_with_response(payload: dict[str, Any]) -> LiveNppesAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LiveNppesAdapter(client=client)


def test_not_found_shape_reports_exists_false() -> None:
    adapter = _adapter_with_response(_NOT_FOUND_RESPONSE)
    result = adapter.lookup("9999999999")
    assert result == {"exists": False}


def test_found_shape_extracts_name_status_and_primary_taxonomy() -> None:
    adapter = _adapter_with_response(_FOUND_RESPONSE)
    result = adapter.lookup("1000000004")
    assert result["exists"] is True
    assert result["name"] == "SAMPLE PROVIDER"
    assert result["status"] == "A"
    assert result["taxonomy_descriptions"] == ["Counselor, Professional", "Psychiatric Unit"]


def test_lookup_caches_within_the_same_adapter_instance() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=_NOT_FOUND_RESPONSE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = LiveNppesAdapter(client=client)
    adapter.lookup("9999999999")
    adapter.lookup("9999999999")
    assert calls["count"] == 1


_RUN_LIVE = os.environ.get("RUN_LIVE_REGISTRY_TESTS") == "1"


@pytest.mark.skipif(not _RUN_LIVE, reason="set RUN_LIVE_REGISTRY_TESTS=1 to hit the real NPPES API")
def test_a_fake_npi_is_not_found_against_the_real_live_api() -> None:
    adapter = LiveNppesAdapter()
    result = adapter.lookup("9999999999")
    assert result == {"exists": False}
