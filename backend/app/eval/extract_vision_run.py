"""Vision-enabled Extract eval (M6.1 #3): the two documents in the
12-packet corpus with NO text layer at all - benign-2-rotated-scan's
genuine (if rotated) license scan, and defective-7's illegible
license-slot scan (D09+D10: actually a CV, badly degraded) - get
structurally 0% coverage from the text-only extract_modes (app/eval/
extract_run.py), since there is no document_text for them to read.
This module attaches the real page image instead, letting Claude's
vision read it directly.

Both are scored against the license slot's ground truth
(packet["facts"]["license"]) regardless of what was actually uploaded
there - deliberate, unlike extract_run.py's `_SCORED_SLOTS` gate: the
point here is specifically to confirm a vision-capable model reports
"unknown" rather than hallucinating, whether the image is merely hard
to read (D10) or isn't a license at all (D09). Kept as its own mode
set, never folded into extract_run.py's scoring, so the
already-reported baseline/haiku/sonnet/opus numbers there are never
retroactively changed by this addition.

Cross-platform note: app/backends/extract_cache.py keys an
image-bearing input on sha256(image bytes), not the bytes themselves -
this makes the CACHE LOOKUP cheap and precise, but does not by itself
guarantee the *same* bytes (and therefore the same key) across
platforms. These two source PNGs are rendered by Pillow at corpus-
build time (app/eval/generator/documents.py's write_scan_image) and
are NOT committed as static files (eval/fixtures/packets/ is
gitignored, regenerated per run) - if a different OS's Pillow/zlib
build produces different compressed bytes for logically-identical
pixels, a replay-mode run there would miss this cache. app/eval/
extract_run.py's `except (ValueError, MissingFixtureError)` handling
(reused here) converts that into "nothing extracted" for that one
document rather than crashing the whole eval, but it would not be
scored on that platform. Verified only that regeneration is
byte-stable *within* one platform (run twice, diffed, identical);
true cross-OS stability is unverified from this environment - flagged
honestly rather than assumed.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Literal

from app.backends.extract_cache import ExtractionBackend, MissingFixtureError
from app.backends.extract_types import ExtractInput, LicenseExtraction
from app.core.extract_verify import verify_license_extraction
from app.eval.baseline_extraction import extract_baseline_facts
from app.eval.extract_run import LICENSE_FIELDS, flat_field_results
from app.eval.extract_types import DocumentExtraction, ExtractModeResult

logger = logging.getLogger(__name__)

_IMAGE_MEDIA_TYPES: dict[str, Literal["image/png", "image/jpeg"]] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_MEDIA_TYPES


def build_vision_extract_input(packet: dict[str, Any], fixtures_root: Path) -> ExtractInput | None:
    """None when this packet's license slot isn't an image at all (every
    other packet in the corpus) - the caller skips those entirely."""
    rel_path = packet["documents"].get("license")
    if rel_path is None:
        return None
    full_path = fixtures_root / rel_path
    if not _is_image_file(full_path):
        return None
    image_bytes = full_path.read_bytes()
    return ExtractInput(
        doc_id="doc-license",
        kind="license",
        filename=f"{packet['packet_id']}/{full_path.name}",
        document_text="",
        image_b64=base64.b64encode(image_bytes).decode("ascii"),
        image_media_type=_IMAGE_MEDIA_TYPES[full_path.suffix.lower()],
    )


def run_extract_vision(
    ground_truth: dict[str, Any],
    fixtures_root: Path,
    *,
    mode_name: str,
    backend: ExtractionBackend,
) -> ExtractModeResult:
    documents: list[DocumentExtraction] = []
    for packet in ground_truth["packets"]:
        extract_input = build_vision_extract_input(packet, fixtures_root)
        if extract_input is None:
            continue

        try:
            result = backend.extract(extract_input)
        except (ValueError, MissingFixtureError) as exc:
            logger.warning(
                "vision extract failed for packet=%s backend=%s: %s",
                packet["packet_id"],
                backend.name,
                exc,
            )
            documents.append(
                DocumentExtraction(
                    packet_id=packet["packet_id"],
                    slot="license",
                    kind="license",
                    decided_by=backend.name,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    cost_known=True,
                    latency_ms=0.0,
                    simulated=False,
                    field_results=[],
                )
            )
            continue

        assert isinstance(result.fields, LicenseExtraction)
        # No text layer at all (that's the whole premise of this
        # module) - app/core/citations.py's verify_field marks every
        # known field quote_verified=False, same as any other image.
        verified = verify_license_extraction(result.fields, document_text=None)
        field_results = flat_field_results(
            "license", LICENSE_FIELDS, packet["facts"]["license"], verified
        )
        documents.append(
            DocumentExtraction(
                packet_id=packet["packet_id"],
                slot="license",
                kind="license",
                decided_by=result.decided_by,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                cost_known=result.cost_known,
                latency_ms=result.latency_ms,
                simulated=result.simulated,
                field_results=field_results,
            )
        )

    final_mode = f"{mode_name}-SIMULATED" if any(d.simulated for d in documents) else mode_name
    return ExtractModeResult(mode=final_mode, documents=documents)


def run_extract_vision_baseline(
    ground_truth: dict[str, Any], fixtures_root: Path, *, mode_name: str = "extract-vision-baseline"
) -> ExtractModeResult:
    """M3's regex baseline has no OCR/vision at all - included
    "alongside" purely to make that contrast explicit in the report
    (0% coverage by construction, not a bug)."""
    documents: list[DocumentExtraction] = []
    for packet in ground_truth["packets"]:
        extract_input = build_vision_extract_input(packet, fixtures_root)
        if extract_input is None:
            continue
        facts, _notes = extract_baseline_facts(packet, fixtures_root)
        field_results = flat_field_results(
            "license", LICENSE_FIELDS, packet["facts"]["license"], _as_verified_dict(facts.license)
        )
        documents.append(
            DocumentExtraction(
                packet_id=packet["packet_id"],
                slot="license",
                kind="license",
                decided_by="code",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                cost_known=True,
                latency_ms=0.0,
                simulated=False,
                field_results=field_results,
            )
        )
    return ExtractModeResult(mode=mode_name, documents=documents)


def _as_verified_dict(license_facts: Any) -> dict[str, Any]:
    """Adapts baseline_extraction.py's plain LicenseFacts (no
    VerifiedField wrapper - it's not a citation-based extractor) into
    the same {field_name: object-with-.value/.status/.quote_verified}
    shape flat_field_results expects, so both the Claude and baseline
    rows can share one scoring function."""

    class _Shim:
        def __init__(self, value: Any) -> None:
            self.value = None if value is None else str(value)
            self.status = "unknown" if value is None else "known"
            self.quote_verified = True

    return {name: _Shim(getattr(license_facts, name)) for name in LICENSE_FIELDS}
