"""The defect catalog (SPEC.md section 10): D01-D15.

This module is documentation + a coverage checklist — the single place
that names every defect id. `packets.py` plants these into packet specs;
`expected.py` maps each one to the Finding(s) it should flip away from the
clean baseline. Keeping the id -> description mapping here (rather than
scattered across packet definitions) is what lets a test assert "every
defect in the catalog appears in at least one packet" without re-deriving
the catalog from the packets themselves.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Defect:
    id: str
    description: str


DEFECT_CATALOG: dict[str, Defect] = {
    d.id: d
    for d in [
        Defect("D01", "license expired at target date"),
        Defect("D02", "license expiring within 90 days"),
        Defect("D03", "COI expired"),
        Defect("D04", "COI limits below $100k/$300k"),
        Defect("D05", "genuine name mismatch (license vs profile/NPPES fixture)"),
        Defect("D06", "LPC Associate submitting as independent"),
        Defect("D07", "Associate whose supervisor's license is expired"),
        Defect("D08", "CV gap over 6 months with no explanation"),
        Defect("D09", "wrong document in slot (CV uploaded as license)"),
        Defect("D10", "illegible scan"),
        Defect("D11", "NPI taxonomy not counselor"),
        Defect("D12", "LEIE hit (synthetic injected row)"),
        Defect("D13", "COI insured name unrelated to provider"),
        Defect("D14", "prompt-injection text inside the CV"),
        Defect("D15", "invalid NPI check digit"),
    ]
}
