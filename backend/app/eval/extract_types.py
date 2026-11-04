"""Extract-stage eval types (SPEC.md section 14, M6: "field-level
accuracy and coverage per field and per tier... compared against the
M3 regex baseline"). Parallel to app/eval/classify_types.py, but one
level more granular: a DocumentExtraction carries a FieldResult per
extracted field, not just a single predicted/true pair.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FieldResult(BaseModel):
    field: str  # e.g. "license.holder_name" or "cv.positions[0].title"
    expected: str | None  # ground truth value (from the packet's ground-truth facts)
    predicted: str | None  # VerifiedField.value, or None when status == "unknown"
    status: Literal["known", "unknown"]
    quote_verified: bool
    # expected == predicted (both None counts as correct - "nothing
    # there, nothing extracted" is not a miss).
    correct: bool


class DocumentExtraction(BaseModel):
    packet_id: str
    slot: str
    kind: str
    decided_by: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_known: bool
    latency_ms: float
    simulated: bool
    field_results: list[FieldResult]


class ExtractModeResult(BaseModel):
    # "-SIMULATED" appended whenever any document in this mode came
    # from a simulated fixture, mirroring ClassifyModeResult.
    mode: str
    documents: list[DocumentExtraction]
