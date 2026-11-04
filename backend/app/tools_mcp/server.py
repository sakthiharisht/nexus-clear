"""MCP server (SPEC.md section 7.6): `nppes_lookup`, `leie_check`,
`tx_license_lookup`, `get_rule`, each returning an EvidenceRecord.

Verified 2026-11-04 against the installed `mcp` package (2.3.0, added
via `uv add "mcp[cli]"`) by direct introspection, not just reading
docs - a first WebFetch of the SDK's GitHub page claimed an import
path that turned out subtly wrong once actually tried:
- **FastMCP was renamed to `MCPServer` in mcp 2.x**
  (`from mcp.server.mcpserver import MCPServer`) - confirmed by the
  package's own `ModuleNotFoundError` message when the old
  `mcp.server.fastmcp` path was tried first. SPEC.md/CLAUDE.md's
  "FastMCP" references predate this rename; this module uses the
  current real name.
- `@mcp.tool()` returns the original function unmodified (directly
  unit-testable as a plain Python call) and registers it internally.
- `await mcp.call_tool(name, arguments)` executes a registered tool;
  `.structured_content` is the return value's own dict shape (not
  wrapped) for a dict/BaseModel return, `.content` is a JSON-rendered
  TextContent list, `.is_error: bool`.
- `await mcp.list_tools()` returns `Tool` objects with `.name`,
  `.description`, `.input_schema` (a JSON Schema dict) - directly
  usable as Anthropic's `tools` parameter shape (app/reconcile/
  investigator.py).
- `mcp.run(transport="stdio"|"sse"|"streamable-http")` runs it as a
  real standalone server process.

Modes (SPEC 7.6): FIXTURE (default) reads
eval/fixtures/registry/{nppes,tx_license,leie}.json - the same files
app/eval/baseline_reconcile.py (M3) already reads; that format is
SPEC's own "provisional preview... not a spec," and it already
carries what every tool needs, so this reuses it rather than
reshaping it for reshaping's sake. LIVE switches nppes_lookup and
leie_check to the real public NPPES API / LEIE CSV
(app/tools_mcp/live_nppes.py, live_leie.py). `tx_license_lookup`
stays FIXTURE-only in both modes - BHEC (the TX Behavioral Health
Executive Council) has no verified programmatic access (SPEC 7.6);
its EvidenceRecord says so explicitly rather than silently behaving
as if it were live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer

from app.rules.loader import load_rule_pack
from app.tools_mcp.evidence import EvidenceRecord, make_evidence_record
from app.tools_mcp.fixtures import load_registry_fixtures
from app.tools_mcp.live_leie import LiveLeieAdapter
from app.tools_mcp.live_nppes import LiveNppesAdapter

ToolMode = Literal["fixture", "live"]


def build_mcp_server(
    *,
    mode: ToolMode,
    fixtures_root: Path,
    rule_pack_path: Path,
    leie_cache_path: Path,
    http_client: httpx.Client | None = None,
) -> MCPServer:
    mcp = MCPServer("nexus-clear-reconcile")

    registry_fixtures = load_registry_fixtures(fixtures_root)
    pack = load_rule_pack(rule_pack_path)
    live_nppes = LiveNppesAdapter(client=http_client) if mode == "live" else None
    live_leie = LiveLeieAdapter(leie_cache_path, client=http_client) if mode == "live" else None

    @mcp.tool()
    def nppes_lookup(npi: str) -> EvidenceRecord:
        """Look up a provider's NPPES NPI Registry record by NPI."""
        if mode == "live":
            assert live_nppes is not None
            payload = live_nppes.lookup(npi)
            return make_evidence_record("nppes", npi, payload, mode="live")

        entry = registry_fixtures["nppes"].get(npi)
        payload = dict(entry) if entry is not None else {"exists": False}
        return make_evidence_record("nppes", npi, payload, mode="fixture")

    @mcp.tool()
    def leie_check(name: str, npi: str | None = None) -> EvidenceRecord:
        """Check the OIG List of Excluded Individuals/Entities (LEIE)
        for a possible match on `name`, optionally narrowed by `npi`."""
        if mode == "live":
            assert live_leie is not None
            payload = live_leie.check(name, npi=npi)
            return make_evidence_record("leie", name, payload, mode="live")

        entry = registry_fixtures["leie"].get(name)
        payload = dict(entry) if entry is not None else {"possible_match": False, "npi": None}
        return make_evidence_record("leie", name, payload, mode="fixture")

    @mcp.tool()
    def tx_license_lookup(license_number: str) -> EvidenceRecord:
        """Look up a Texas LPC license by license number. FIXTURE-only
        always: the Texas Behavioral Health Executive Council (BHEC)
        has no verified programmatic access (SPEC.md section 7.6)."""
        entry = registry_fixtures["tx_license"].get(license_number)
        payload: dict[str, Any] = dict(entry) if entry is not None else {"status": None}
        payload["_note"] = "tx_license_lookup is fixture-only: BHEC has no verified live API"
        return make_evidence_record("tx_license", license_number, payload, mode="fixture")

    @mcp.tool()
    def get_rule(rule_id: str) -> EvidenceRecord:
        """Look up a rule's full definition from the loaded rule pack
        by its id."""
        rule = next((r for r in pack.rules if r.id == rule_id), None)
        payload = rule.model_dump(mode="json") if rule is not None else {}
        return make_evidence_record("rule_pack", rule_id, payload, mode="fixture")

    return mcp
