from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

from app.tools_mcp.server import build_mcp_server

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures" / "registry"
RULE_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"


@pytest.fixture
def fixture_mcp(tmp_path: Path) -> MCPServer:
    return build_mcp_server(
        mode="fixture",
        fixtures_root=REGISTRY_FIXTURES_ROOT,
        rule_pack_path=RULE_PACK_PATH,
        leie_cache_path=tmp_path / "leie.csv",
    )


async def _call(mcp: MCPServer, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(name, args)
    assert isinstance(result, CallToolResult)
    assert result.is_error is False
    content: dict[str, Any] = result.structured_content
    return content


@pytest.mark.anyio
async def test_nppes_lookup_returns_a_real_fixture_entry(fixture_mcp: MCPServer) -> None:
    content = await _call(fixture_mcp, "nppes_lookup", {"npi": "1000000004"})
    assert content["source"] == "nppes"
    assert content["query"] == "1000000004"
    assert content["mode"] == "fixture"
    assert content["payload"]["exists"] is True
    assert "record_hash" in content
    assert "fetched_at" in content


@pytest.mark.anyio
async def test_nppes_lookup_reports_not_found_for_an_unknown_npi(fixture_mcp: MCPServer) -> None:
    content = await _call(fixture_mcp, "nppes_lookup", {"npi": "0000000000"})
    assert content["payload"] == {"exists": False}


@pytest.mark.anyio
async def test_tx_license_lookup_always_notes_it_is_fixture_only(fixture_mcp: MCPServer) -> None:
    content = await _call(fixture_mcp, "tx_license_lookup", {"license_number": "LPC-100000"})
    assert content["mode"] == "fixture"
    assert "fixture-only" in content["payload"]["_note"]


@pytest.mark.anyio
async def test_leie_check_returns_a_fixture_entry(fixture_mcp: MCPServer) -> None:
    content = await _call(fixture_mcp, "leie_check", {"name": "Christopher Lee"})
    assert content["source"] == "leie"
    assert content["payload"]["possible_match"] is False


@pytest.mark.anyio
async def test_get_rule_returns_the_full_rule_definition(fixture_mcp: MCPServer) -> None:
    content = await _call(fixture_mcp, "get_rule", {"rule_id": "R-LIC-004"})
    assert content["payload"]["kind"] == "name_match"
    assert content["payload"]["params"]["min_probability"] == 0.9


@pytest.mark.anyio
async def test_get_rule_returns_empty_payload_for_an_unknown_rule_id(
    fixture_mcp: MCPServer,
) -> None:
    content = await _call(fixture_mcp, "get_rule", {"rule_id": "R-NOT-REAL"})
    assert content["payload"] == {}


@pytest.mark.anyio
async def test_record_hash_is_stable_for_identical_payloads(fixture_mcp: MCPServer) -> None:
    first = await _call(fixture_mcp, "nppes_lookup", {"npi": "1000000004"})
    second = await _call(fixture_mcp, "nppes_lookup", {"npi": "1000000004"})
    assert first["record_hash"] == second["record_hash"]


@pytest.mark.anyio
async def test_record_hash_differs_for_different_payloads(fixture_mcp: MCPServer) -> None:
    a = await _call(fixture_mcp, "nppes_lookup", {"npi": "1000000004"})
    b = await _call(fixture_mcp, "nppes_lookup", {"npi": "1000000012"})
    assert a["record_hash"] != b["record_hash"]


def test_all_three_registry_fixture_files_are_valid_json() -> None:
    for name in ("nppes", "tx_license", "leie"):
        data = json.loads((REGISTRY_FIXTURES_ROOT / f"{name}.json").read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data
