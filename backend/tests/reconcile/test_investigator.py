"""Unit tests for Investigator's loop mechanics against a fake Claude
client (no real network) - the real MCP tool execution underneath is
the genuine fixture-mode server, so only the model side is faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from app.reconcile.investigator import (
    SUBMIT_TOOL_NAME,
    Investigator,
    NameMatchTask,
    RegistryTask,
)
from app.tools_mcp.server import build_mcp_server

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures" / "registry"
RULE_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"


@dataclass
class _FakeBlock:
    type: str
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    id: str = "block-1"


@dataclass
class _FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 10


@dataclass
class _FakeResponse:
    content: list[_FakeBlock]
    usage: _FakeUsage = field(default_factory=_FakeUsage)


@pytest.fixture
def fixture_mcp(tmp_path: Path) -> MCPServer:
    return build_mcp_server(
        mode="fixture",
        fixtures_root=REGISTRY_FIXTURES_ROOT,
        rule_pack_path=RULE_PACK_PATH,
        leie_cache_path=tmp_path / "leie.csv",
    )


class _FakeMessagesAPI:
    """Always requests another nppes_lookup call, unless tool_choice
    forces the submit tool - simulating a model that would loop
    forever calling tools without the Investigator's own backstop."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        tool_choice = kwargs.get("tool_choice", {})
        if tool_choice.get("type") == "tool" and tool_choice.get("name") == SUBMIT_TOOL_NAME:
            return _FakeResponse(
                content=[
                    _FakeBlock(
                        type="tool_use",
                        name=SUBMIT_TOOL_NAME,
                        input={
                            "registry_conclusions": [
                                {"rule_id": "R-ID-002", "exists": True, "checks": {}}
                            ]
                        },
                        id="submit-1",
                    )
                ]
            )
        return _FakeResponse(
            content=[
                _FakeBlock(
                    type="tool_use",
                    name="nppes_lookup",
                    input={"npi": "1000000004"},
                    id=f"call-{len(self.calls)}",
                )
            ]
        )


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessagesAPI()


def test_request_limit_is_enforced(fixture_mcp: MCPServer) -> None:
    """A model that always wants to call another tool is forced to
    submit once max_tool_calls real tool calls have been made - the
    loop terminates, it never runs away."""
    fake_client = _FakeClient()
    investigator = Investigator(
        fixture_mcp,
        model="claude-haiku-5-5",
        client=fake_client,  # type: ignore[arg-type]
        max_tool_calls=3,
    )

    result = investigator.investigate(
        name_match_tasks=[],
        registry_tasks=[
            RegistryTask(
                rule_id="R-ID-002",
                kind="registry_flags_check",
                tool="nppes_lookup",
                query={"npi": "1000000004"},
            )
        ],
    )

    assert result.tool_calls_made == 3
    assert result.aborted_reason is None  # forced submission, not an abort
    assert len(result.registry_conclusions) == 1


def test_a_well_behaved_model_submits_without_hitting_the_limit(fixture_mcp: MCPServer) -> None:
    class _ImmediateSubmitAPI:
        def create(self, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse(
                content=[
                    _FakeBlock(
                        type="tool_use",
                        name=SUBMIT_TOOL_NAME,
                        input={
                            "name_match_conclusions": [
                                {"rule_id": "R-LIC-004", "probability": 0.95}
                            ]
                        },
                        id="submit-1",
                    )
                ]
            )

    class _Client:
        messages = _ImmediateSubmitAPI()

    investigator = Investigator(
        fixture_mcp,
        model="claude-haiku-5-5",
        client=_Client(),  # type: ignore[arg-type]
        max_tool_calls=6,
    )
    result = investigator.investigate(
        name_match_tasks=[
            NameMatchTask(
                rule_id="R-LIC-004",
                left_label="license.holder_name",
                left_value="Jon Smith",
                right_label="profile.legal_name",
                right_value="Jonathan Smith",
            )
        ],
        registry_tasks=[],
    )
    assert result.tool_calls_made == 0
    assert result.name_match_conclusions[0].probability == 0.95


def test_no_tasks_returns_immediately_without_calling_the_model(fixture_mcp: MCPServer) -> None:
    fake_client = _FakeClient()
    investigator = Investigator(
        fixture_mcp, model="claude-haiku-5-5", client=fake_client  # type: ignore[arg-type]
    )
    result = investigator.investigate(name_match_tasks=[], registry_tasks=[])
    assert result == result.__class__()
    assert fake_client.messages.calls == []
