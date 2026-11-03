"""Top-level entry point: generate all 12 synthetic packets and write
eval/fixtures/ground_truth.json + eval/fixtures/registry/*.json +
eval/fixtures/packets/** (SPEC.md section 10).

Deterministic from `seed` — see tests/eval/test_determinism.py. Run for
real (writes into the repo's /eval/fixtures) with:
    uv run python -m app.eval.generator.build
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from faker import Faker

from app.eval.generator.defects import DEFECT_CATALOG
from app.eval.generator.packets import PACKET_SPECS, TARGET_DATE, build_packet

DEFAULT_SEED = 20261103
RULE_PACK_VERSION = "0.2.0"


def generate_all(seed: int, output_root: Path) -> dict[str, Any]:
    """Build all 12 packets and write fixtures under `output_root`. Returns
    the ground-truth manifest dict that was written, so callers/tests don't
    need to re-read the file to inspect what was produced."""
    Faker.seed(seed)
    fake = Faker()

    packets_payload: list[dict[str, Any]] = []
    registry_merged: dict[str, dict[str, Any]] = {"nppes": {}, "tx_license": {}, "leie": {}}

    for index, spec in enumerate(PACKET_SPECS):
        built = build_packet(spec, index, fake, output_root)

        for tool, entries in built.registry_fixtures.items():
            registry_merged[tool].update(entries)

        packets_payload.append(
            {
                "packet_id": built.packet_id,
                "kind": built.kind,
                "defect_ids": built.defect_ids,
                # By convention (see app/eval/metrics.py's
                # primary_defect_detected_rate), the first-listed defect is
                # this packet's primary scenario; the rest are secondary/
                # co-occurring. None for clean/benign packets.
                "primary_defect": built.defect_ids[0] if built.defect_ids else None,
                "description": built.description,
                "target_date": built.target_date.isoformat(),
                "documents": {
                    slot: path.relative_to(output_root).as_posix()
                    for slot, path in built.document_paths.items()
                },
                "facts": built.facts.model_dump(mode="json"),
                "expected_findings": dict(built.expected_findings),
            }
        )

    manifest: dict[str, Any] = {
        "seed": seed,
        "rule_pack_version": RULE_PACK_VERSION,
        "target_date": TARGET_DATE.isoformat(),
        "defect_catalog": {defect_id: d.description for defect_id, d in DEFECT_CATALOG.items()},
        "packets": packets_payload,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (output_root / "ground_truth.json").write_text(manifest_text, encoding="utf-8")

    registry_dir = output_root / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    for tool, entries in registry_merged.items():
        entries_text = json.dumps(entries, indent=2, sort_keys=True) + "\n"
        (registry_dir / f"{tool}.json").write_text(entries_text, encoding="utf-8")

    return manifest


def main() -> None:  # pragma: no cover - thin CLI wrapper, exercised via generate_all in tests
    repo_root = Path(__file__).resolve().parents[4]
    output_root = repo_root / "eval" / "fixtures"
    generate_all(DEFAULT_SEED, output_root)
    print(f"Wrote fixtures to {output_root}")


if __name__ == "__main__":  # pragma: no cover
    main()
