from __future__ import annotations

from pathlib import Path

import pypdf

from app.eval.generator.hard_extraction_set import all_cases, generate_hard_extraction_set


def test_all_cases_has_between_20_and_30_cases() -> None:
    cases = all_cases()
    assert 20 <= len(cases) <= 30


def test_case_ids_are_unique() -> None:
    cases = all_cases()
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))


def test_every_category_is_represented() -> None:
    categories = {c.category for c in all_cases()}
    assert categories == {
        "noisy_layout",
        "narrative",
        "multi_page",
        "unusual_cv",
        "ambiguous_date",
        "name_suffix",
    }


def test_cv_cases_use_expected_positions_not_expected_fields() -> None:
    for case in all_cases():
        if case.kind == "cv":
            assert case.expected_positions
            assert case.expected_fields == {}


def test_license_and_coi_cases_use_expected_fields() -> None:
    for case in all_cases():
        if case.kind in ("license", "coi"):
            assert any(v is not None for v in case.expected_fields.values())


def test_generate_hard_extraction_set_renders_every_case_and_a_manifest(
    tmp_path: Path,
) -> None:
    manifest = generate_hard_extraction_set(tmp_path)
    cases = all_cases()
    assert len(manifest) == len(cases)
    for entry in manifest:
        pdf_path = tmp_path / entry["path"]
        assert pdf_path.exists()
        reader = pypdf.PdfReader(str(pdf_path))
        assert len(reader.pages) >= 1


def test_multi_page_cases_actually_render_multiple_pages(tmp_path: Path) -> None:
    generate_hard_extraction_set(tmp_path)
    multi_page_cases = [c for c in all_cases() if c.category == "multi_page"]
    assert multi_page_cases
    for case in multi_page_cases:
        reader = pypdf.PdfReader(str(tmp_path / f"hard_extraction/{case.case_id}.pdf"))
        assert len(reader.pages) == len(case.pages)
        assert len(reader.pages) >= 2


def test_rendering_is_deterministic_across_two_runs(tmp_path: Path) -> None:
    import hashlib

    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    generate_hard_extraction_set(out1)
    generate_hard_extraction_set(out2)

    for case in all_cases():
        rel = f"hard_extraction/{case.case_id}.pdf"
        hash1 = hashlib.sha256((out1 / rel).read_bytes()).hexdigest()
        hash2 = hashlib.sha256((out2 / rel).read_bytes()).hexdigest()
        assert hash1 == hash2, f"{case.case_id} is not deterministic"


def test_ambiguous_date_case_reads_as_us_mm_dd_format() -> None:
    case = next(c for c in all_cases() if c.case_id == "ambigdate-1")
    assert case.expected_fields["issue_date"] == "2020-03-04"
