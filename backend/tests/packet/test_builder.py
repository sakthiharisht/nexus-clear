"""Tests for app/packet/builder.py: the packet must only ever carry
verified-known field values (CLAUDE.md invariant 2) - an unknown field
is omitted entirely, never a guess or a blank placeholder.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.orm import Extraction
from app.packet.builder import PACKET_LABEL, STILL_TO_DO_IN_CAQH, build_packet


def _extraction(schema_version: str, fields: dict[str, object]) -> Extraction:
    return Extraction(
        document_id=uuid4(), schema_version=schema_version, fields=fields, model="claude"
    )


def _known(value: object) -> dict[str, object]:
    return {"status": "known", "value": value}


def _unknown() -> dict[str, object]:
    return {"status": "unknown", "value": None}


def test_a_known_flat_field_is_included() -> None:
    extraction = _extraction("license", {"holder_name": _known("Christopher Lee")})
    packet = build_packet(uuid4(), provider_profile={}, extractions=[extraction])
    assert packet.license == {"holder_name": "Christopher Lee"}


def test_an_unknown_flat_field_is_omitted_not_guessed() -> None:
    extraction = _extraction(
        "license", {"holder_name": _known("Christopher Lee"), "license_number": _unknown()}
    )
    packet = build_packet(uuid4(), provider_profile={}, extractions=[extraction])
    assert "license_number" not in packet.license


def test_cv_positions_keep_only_verified_sub_fields() -> None:
    extraction = _extraction(
        "cv",
        {
            "name": _known("Christopher Lee"),
            "positions": [
                {
                    "title": _known("Associate Counselor"),
                    "employer": _unknown(),
                    "start": _known("2020-11-18"),
                    "end": _unknown(),
                }
            ],
            "education": [],
        },
    )
    packet = build_packet(uuid4(), provider_profile={}, extractions=[extraction])
    assert packet.cv["name"] == "Christopher Lee"
    assert packet.cv["positions"] == [{"title": "Associate Counselor", "start": "2020-11-18"}]


def test_an_unknown_schema_version_is_ignored() -> None:
    extraction = _extraction("education", {"name": _known("Christopher Lee")})
    packet = build_packet(uuid4(), provider_profile={}, extractions=[extraction])
    assert packet.license == {}
    assert packet.coi == {}
    assert packet.cv == {}


def test_profile_passes_through_as_is() -> None:
    profile: dict[str, object] = {"legal_name": "Christopher Lee", "npi": "1000000004"}
    packet = build_packet(uuid4(), provider_profile=profile, extractions=[])
    assert packet.profile == profile


def test_the_packet_label_never_claims_to_be_a_real_caqh_submission() -> None:
    packet = build_packet(uuid4(), provider_profile={}, extractions=[])
    assert packet.label == PACKET_LABEL
    assert "not a" in PACKET_LABEL.lower()


def test_still_to_do_in_caqh_is_always_present_regardless_of_case_content() -> None:
    """M9.1 #3/#4: this section is static - not derived from the case's
    profile or extractions - so it must be identical whether the
    packet is fully verified or completely empty."""
    empty = build_packet(uuid4(), provider_profile={}, extractions=[])
    full_extraction = _extraction(
        "license",
        {
            "holder_name": _known("Christopher Lee"),
            "license_number": _known("LPC-100000"),
        },
    )
    full = build_packet(
        uuid4(),
        provider_profile={"legal_name": "Christopher Lee", "npi": "1000000004"},
        extractions=[full_extraction],
    )
    assert empty.still_to_do_in_caqh == STILL_TO_DO_IN_CAQH
    assert full.still_to_do_in_caqh == STILL_TO_DO_IN_CAQH
    assert len(STILL_TO_DO_IN_CAQH) > 0


def test_still_to_do_in_caqh_covers_authorization_and_attestation_and_is_flagged() -> None:
    packet = build_packet(uuid4(), provider_profile={}, extractions=[])
    descriptions = " ".join(step.description.lower() for step in packet.still_to_do_in_caqh)
    assert "authorize" in descriptions
    assert "attest" in descriptions
    # Every item is a third-party-sourced policy claim about what CAQH
    # requires, not something this app verified against CAQH's own
    # documentation - must stay visibly flagged (CLAUDE.md: items marked
    # needs_verification must stay visible in the UI).
    assert all(step.needs_verification for step in packet.still_to_do_in_caqh)
    assert all(step.source_id for step in packet.still_to_do_in_caqh)


def test_still_to_do_in_caqh_never_claims_the_uncollected_sections_were_filled() -> None:
    """Even when the packet has verified license/COI/CV data, the
    CAQH-sections list must still say those other sections (practice
    locations, hospital affiliations, etc.) are not collected - this
    app filling in license/COI/CV must never be read as filling in the
    rest of a CAQH profile too."""
    extraction = _extraction("license", {"holder_name": _known("Christopher Lee")})
    packet = build_packet(uuid4(), provider_profile={}, extractions=[extraction])
    not_collected = [s for s in packet.still_to_do_in_caqh if "not collected" in s.description]
    assert len(not_collected) >= 5
