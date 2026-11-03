"""DecisionBackend stage boundary (SPEC.md section 7.2): the typed
input Classify hands to a backend, and the typed result every backend
(Jev, Claude) returns in the same shape regardless of which one
answered.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# SPEC.md section 7.2's fixed doc_type choice set (app/eval/generator/
# mutations.py's SLOT_DOC_TYPES has the same 5 real types - "other" is
# Classify's own catch-all for anything that isn't one of them).
DOC_TYPES: tuple[str, ...] = (
    "texas_lpc_license",
    "malpractice_coi",
    "cv",
    "w9",
    "degree_transcript",
    "other",
)

DocType = Literal[
    "texas_lpc_license", "malpractice_coi", "cv", "w9", "degree_transcript", "other"
]


class ClassifyInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot: str
    filename: str
    allowed_doc_types: list[str]
    page1_text: str = ""
    # Raw base64 (no "data:" prefix) - present only when page1_text is
    # empty/unreliable (no text layer) or the backend is vision-capable
    # and an image strengthens the decision.
    page1_image_b64: str | None = None
    page1_image_media_type: Literal["image/png", "image/jpeg"] | None = None


class ClassificationResult(BaseModel):
    doc_type: str
    probabilities: dict[str, float]
    legible: float
    slot_match: bool
    decided_by: Literal["jev", "claude"]
    cost_usd: float = 0.0
    latency_ms: float = 0.0
