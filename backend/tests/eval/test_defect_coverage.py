"""M2 accept criterion: the manifest covers D01-D15."""

from app.eval.generator.defects import DEFECT_CATALOG
from app.eval.generator.packets import PACKET_SPECS


def test_every_catalog_defect_appears_in_at_least_one_packet() -> None:
    planted = {defect_id for spec in PACKET_SPECS for defect_id in spec.defect_ids}
    assert planted == set(DEFECT_CATALOG.keys())


def test_twelve_packets_with_the_spec_composition() -> None:
    assert len(PACKET_SPECS) == 12
    by_kind = {kind: 0 for kind in ("clean", "benign", "defective")}
    for spec in PACKET_SPECS:
        by_kind[spec.kind] += 1
    assert by_kind == {"clean": 2, "benign": 2, "defective": 8}


def test_clean_and_benign_packets_plant_no_defects() -> None:
    for spec in PACKET_SPECS:
        if spec.kind in ("clean", "benign"):
            assert spec.defect_ids == [], spec.packet_id


def test_defective_packets_plant_one_to_three_defects() -> None:
    for spec in PACKET_SPECS:
        if spec.kind == "defective":
            assert 1 <= len(spec.defect_ids) <= 3, spec.packet_id


def test_packet_ids_are_unique() -> None:
    ids = [spec.packet_id for spec in PACKET_SPECS]
    assert len(ids) == len(set(ids))
