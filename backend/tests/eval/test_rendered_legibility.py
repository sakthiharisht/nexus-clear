"""Confidence check that the D10 defect's rendered scan is actually
illegible as an *artifact* — not just a hand-asserted `legible_score` in
CaseFacts with no connection to what got drawn to disk.

This is a non-OCR proxy (edge-detection sharpness, normalized against a
clean reference rendering of the same content) — nowhere near a real
legibility assessment, but enough signal to catch the generator claiming
"illegible" while actually producing something readable (the real bug
fixed in app/eval/generator/packets.py's D09+D10 branch ordering was
exactly this kind of artifact/label mismatch).
"""

from pathlib import Path

from faker import Faker
from PIL import Image, ImageFilter, ImageStat

from app.eval.generator import documents as docs
from app.eval.generator.build import DEFAULT_SEED
from app.eval.generator.packets import PACKET_SPECS, TARGET_DATE, BuiltPacket, build_packet
from app.eval.generator.provider import build_provider

# min_score for R-DOC-002 in rules/tx_bcbstx_lpc.yaml.
LEGIBILITY_THRESHOLD = 0.7

# A sharp, undegraded rendering's edge-intensity mean, empirically measured
# (see the module docstring) — the denominator that maps edge intensity
# onto roughly the same [0, 1] scale as the rule's min_score.
_REFERENCE_EDGE_MEAN = 2.6


def measure_legibility(path: Path) -> float:
    image = Image.open(path).convert("L")
    edges = image.filter(ImageFilter.FIND_EDGES)
    edge_mean = ImageStat.Stat(edges).mean[0]
    return min(1.0, edge_mean / _REFERENCE_EDGE_MEAN)


def _build(packet_id: str, output_root: Path) -> BuiltPacket:
    Faker.seed(DEFAULT_SEED)
    fake = Faker()
    for index, spec in enumerate(PACKET_SPECS):
        if spec.packet_id == packet_id:
            return build_packet(spec, index, fake, output_root)
    raise AssertionError(f"no packet spec named {packet_id!r}")


def test_d10_scan_is_measurably_below_the_legibility_threshold(tmp_path: Path) -> None:
    built = _build("defective-7", tmp_path)
    score = measure_legibility(built.document_paths["license"])
    assert score < LEGIBILITY_THRESHOLD
    # And consistent with what CaseFacts asserts for the same document.
    assert built.facts.documents[0].slot == "license"
    assert built.facts.documents[0].legible_score is not None
    assert built.facts.documents[0].legible_score < LEGIBILITY_THRESHOLD


def test_benign_rotated_scan_stays_at_or_above_the_legibility_threshold(tmp_path: Path) -> None:
    built = _build("benign-2-rotated-scan", tmp_path)
    score = measure_legibility(built.document_paths["license"])
    assert score >= LEGIBILITY_THRESHOLD
    assert built.facts.license.doc_id == "doc-license"
    license_doc = next(d for d in built.facts.documents if d.slot == "license")
    assert license_doc.legible_score is not None
    assert license_doc.legible_score >= LEGIBILITY_THRESHOLD


def test_undegraded_scan_measures_near_perfect(tmp_path: Path) -> None:
    # Same shape of content as the license scans above — the metric's
    # reference constant is calibrated against license-content-sized text;
    # a much shorter block would under-measure on content volume alone,
    # independent of any actual degradation.
    Faker.seed(DEFAULT_SEED)
    fake = Faker()
    provider = build_provider(0, TARGET_DATE, fake)
    content = docs.license_content(provider)

    path = tmp_path / "clean.png"
    docs.write_scan_image(path, content)

    assert measure_legibility(path) > 0.9
