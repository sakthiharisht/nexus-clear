"""Classify-stage eval types (SPEC.md section 14's M5 accept criterion:
"eval reports classification accuracy and calibration for Jev vs
Claude tiers"). Separate from app/eval/types.py's PacketResult/
ModeResult, which compare rule-engine Finding status - classify
evaluates a different thing (per-document doc_type prediction), so it
gets its own result shape rather than being forced into that one.
"""

from __future__ import annotations

from pydantic import BaseModel


class DocumentClassification(BaseModel):
    packet_id: str
    slot: str
    expected_doc_type: str  # what the slot wants (static lookup)
    true_doc_type: str  # what the rendered file actually is (ground truth)
    predicted_doc_type: str
    predicted_probability: float  # top-choice probability/confidence
    predicted_legible: float
    predicted_slot_match: bool
    accepted: bool
    escalated: bool
    decided_by: str
    cost_usd: float
    latency_ms: float


class ClassifyModeResult(BaseModel):
    mode: str  # e.g. "classify-jev", "classify-claude"
    documents: list[DocumentClassification]
