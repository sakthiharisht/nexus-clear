"""Shared types for the M3 eval runner — the eval subsystem's own stage
boundary (CLAUDE.md: "Pydantic models at every stage boundary"), separate
from the production pipeline's contracts in app/core/contracts.py.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.contracts import FindingStatus


class PacketResult(BaseModel):
    packet_id: str
    kind: str
    defect_ids: list[str]
    actual: dict[str, FindingStatus]
    expected: dict[str, FindingStatus]
    # baseline mode only: human-readable notes on what couldn't be read
    # (e.g. "license: no text layer, rendered as an image").
    extraction_notes: list[str] = []


class ModeResult(BaseModel):
    mode: str
    packets: list[PacketResult]
