"""M2 accept criterion: the generator is deterministic from its seed."""

from pathlib import Path

from app.eval.generator.build import DEFAULT_SEED, generate_all


def test_ground_truth_json_is_byte_identical_across_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"

    generate_all(DEFAULT_SEED, out_a)
    generate_all(DEFAULT_SEED, out_b)

    assert (out_a / "ground_truth.json").read_bytes() == (out_b / "ground_truth.json").read_bytes()


def test_every_rendered_document_is_byte_identical_across_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"

    generate_all(DEFAULT_SEED, out_a)
    generate_all(DEFAULT_SEED, out_b)

    rendered = sorted(p for p in (out_a / "packets").rglob("*") if p.is_file())
    assert rendered, "generator produced no rendered documents"

    diffs = [
        str(p.relative_to(out_a))
        for p in rendered
        if p.read_bytes() != (out_b / p.relative_to(out_a)).read_bytes()
    ]
    assert diffs == []


def test_registry_fixtures_are_byte_identical_across_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"

    generate_all(DEFAULT_SEED, out_a)
    generate_all(DEFAULT_SEED, out_b)

    for name in ("nppes.json", "tx_license.json", "leie.json"):
        a = (out_a / "registry" / name).read_bytes()
        b = (out_b / "registry" / name).read_bytes()
        assert a == b, name


def test_different_seed_changes_the_provider_data(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"

    manifest_a = generate_all(DEFAULT_SEED, out_a)
    manifest_b = generate_all(DEFAULT_SEED + 1, out_b)

    names_a = {p["facts"]["profile"]["legal_name"] for p in manifest_a["packets"]}
    names_b = {p["facts"]["profile"]["legal_name"] for p in manifest_b["packets"]}
    assert names_a != names_b
