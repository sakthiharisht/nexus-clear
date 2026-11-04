"""Extract stage boundary (SPEC.md section 7.3; app/rules/context.py's
own docstring: "value/confidence/page/quote per field, built in M6").

Two layers per field, matching Classify's split between a raw backend
result and policy's verdict (app/backends/policy.py):
- `ExtractedField`: exactly what the model returns - a raw string
  value, which page it says it's on, and the quote it claims supports
  that value. Dates/money/names are NOT parsed here; SPEC 7.3 is
  explicit that normalization happens in code, never in the model.
- `VerifiedField`: code's verdict after checking that quote against
  the real document text (app/core/citations.py) and normalizing the
  raw value (app/core/normalize.py). `status` is "unknown" whenever
  there's no quote, no value, or (on a text-layer document) the quote
  doesn't actually appear in the text - CLAUDE.md invariant 2: no
  supporting quote means unknown, never guessed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FieldStatus = Literal["known", "unknown"]

ExtractKind = Literal["license", "coi", "cv", "education", "w9"]

# Classify's doc_type -> which extraction schema applies. "other" has
# no entry: a document Classify couldn't place in any known type isn't
# a candidate for any of these 5 schemas (app/eval/baseline_extraction.py's
# M3 baseline makes the same call - it only attempts field extraction
# when the classified type actually matches the slot's expected schema).
DOC_TYPE_TO_EXTRACT_KIND: dict[str, ExtractKind] = {
    "texas_lpc_license": "license",
    "malpractice_coi": "coi",
    "cv": "cv",
    "degree_transcript": "education",
    "w9": "w9",
}


class ExtractedField(BaseModel):
    """The model's raw answer for one field (SPEC 7.3: "Every field:
    value, confidence, page, quote"). `value` is None when the model
    itself reports the field isn't present/visible - still a
    legitimate answer, not a failure to parse."""

    value: str | None = None
    confidence: float | None = None
    page: int | None = None
    quote: str | None = None


class VerifiedField(BaseModel):
    status: FieldStatus
    # Normalized (ISO date string, plain numeric string, trimmed name)
    # when status == "known"; None when "unknown" - never a half-
    # normalized or guessed value.
    value: str | None = None
    # The model's own confidence, carried through unchanged - code
    # does not adjust it based on quote verification. A field demoted
    # to "unknown" for a failed quote check has confidence=None, since
    # there is no verified value left for the number to describe.
    confidence: float | None = None
    page: int | None = None
    quote: str | None = None
    # False whenever the quote couldn't be checked against real
    # document text (no text layer - an image) OR wasn't checked at
    # all (status is already "unknown" for some other reason). True
    # only after an actual substring check against the real text
    # succeeded. A reviewer/downstream rule seeing quote_verified=False
    # on a "known" field knows this came from an unverifiable image,
    # not a demonstrated match - SPEC 7.3's explicit requirement.
    quote_verified: bool = False


class LicenseExtraction(BaseModel):
    holder_name: ExtractedField = ExtractedField()
    license_number: ExtractedField = ExtractedField()
    license_type: ExtractedField = ExtractedField()
    status: ExtractedField = ExtractedField()
    issue_date: ExtractedField = ExtractedField()
    expiration_date: ExtractedField = ExtractedField()
    issuing_board: ExtractedField = ExtractedField()


class CoiExtraction(BaseModel):
    insured_name: ExtractedField = ExtractedField()
    carrier: ExtractedField = ExtractedField()
    policy_number: ExtractedField = ExtractedField()
    effective_date: ExtractedField = ExtractedField()
    expiration_date: ExtractedField = ExtractedField()
    per_occurrence: ExtractedField = ExtractedField()
    aggregate: ExtractedField = ExtractedField()


class CvPositionExtraction(BaseModel):
    title: ExtractedField = ExtractedField()
    employer: ExtractedField = ExtractedField()
    start: ExtractedField = ExtractedField()
    end: ExtractedField = ExtractedField()


class CvExtraction(BaseModel):
    name: ExtractedField = ExtractedField()
    positions: list[CvPositionExtraction] = []
    education: list[ExtractedField] = []


class EducationExtraction(BaseModel):
    name: ExtractedField = ExtractedField()
    degree: ExtractedField = ExtractedField()
    institution: ExtractedField = ExtractedField()
    date: ExtractedField = ExtractedField()


class W9Extraction(BaseModel):
    name: ExtractedField = ExtractedField()
    business_name: ExtractedField = ExtractedField()
    tin_present: ExtractedField = ExtractedField()
    signed: ExtractedField = ExtractedField()


ExtractionFields = (
    LicenseExtraction | CoiExtraction | CvExtraction | EducationExtraction | W9Extraction
)


class ExtractInput(BaseModel):
    """Parallel to app/backends/types.py's ClassifyInput - every
    document in this corpus is single-page (app/eval/generator/
    documents.py's write_pdf calls showPage() exactly once), so
    `document_text` is the whole text layer, not just page 1."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    kind: ExtractKind
    filename: str
    document_text: str = ""
    image_b64: str | None = None
    image_media_type: Literal["image/png", "image/jpeg"] | None = None


class ExtractionResult(BaseModel):
    """Mirrors ClassificationResult's metadata fields (decided_by,
    token/cost/latency accounting, cost_known, simulated) so Extract's
    eval reporting can reuse the same aggregation logic Classify's
    does."""

    kind: ExtractKind
    fields: ExtractionFields
    decided_by: Literal["claude"] = "claude"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True
    latency_ms: float = 0.0
    simulated: bool = False
