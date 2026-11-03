"""Deterministic synthetic provider data (SPEC.md section 10).

One fake person per packet, built from a Faker instance the caller has
already seeded (see build.py) — this module performs no seeding itself, so
it stays a pure function of (index, target_date, fake).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from faker import Faker

from app.eval.generator.npi import synthetic_npi


@dataclass(frozen=True)
class CvPositionSpec:
    title: str
    employer: str
    start: date
    end: date | None  # None = ongoing as of target_date


@dataclass(frozen=True)
class ProviderSpec:
    index: int
    legal_name: str
    practice_name: str
    npi: str

    license_number: str
    license_type: str  # "LPC" or "LPC Associate"
    license_status: str
    license_issue_date: date
    license_expiration_date: date
    issuing_board: str
    license_holder_name: str  # usually == legal_name; D05 diverges it

    coi_carrier: str
    coi_policy_number: str
    coi_effective_date: date
    coi_expiration_date: date
    coi_per_occurrence: float
    coi_aggregate: float
    coi_insured_name: str  # usually == legal_name; D13 diverges it

    positions: list[CvPositionSpec]

    education_institution: str
    education_degree: str
    education_date: date

    w9_business_name: str
    w9_tin: str  # obviously-invalid format — see build_provider

    supervisor_count: int | None = None  # only meaningful for LPC Associates
    supervisor_license_status: str = "Active"  # only meaningful for Associates


def build_provider(index: int, target_date: date, fake: Faker) -> ProviderSpec:
    """A clean, internally-consistent provider: valid license, valid COI,
    continuous 5-year work history, valid NPI. Packets apply defects on top
    of this by overriding specific fields (see packets.py)."""
    legal_name = fake.name()
    practice_name = f"{fake.last_name()} Counseling, PLLC"
    npi = synthetic_npi(index)

    license_issue = target_date - timedelta(days=365 * 6)
    license_expiration = target_date + timedelta(days=365 * 2)

    coi_effective = target_date - timedelta(days=200)
    coi_expiration = target_date + timedelta(days=165)

    # Continuous 5+ year work history ending "today" (ongoing), no gaps.
    job1_start = target_date - timedelta(days=365 * 6)
    job1_end = target_date - timedelta(days=365 * 3)
    job2_start = job1_end
    positions = [
        CvPositionSpec(
            title="Associate Counselor",
            employer=f"{fake.company()} Behavioral Health",
            start=job1_start,
            end=job1_end,
        ),
        CvPositionSpec(
            title="Licensed Professional Counselor",
            employer=f"{fake.company()} Counseling Group",
            start=job2_start,
            end=None,
        ),
    ]

    # Obviously-invalid, clearly-synthetic TIN: the SSA has stated the "000"
    # area is never issued, so 000-xx-xxxx can't collide with a real SSN.
    w9_tin = f"000-{index:02d}-{(1000 + index):04d}"

    return ProviderSpec(
        index=index,
        legal_name=legal_name,
        practice_name=practice_name,
        npi=npi,
        license_number=f"LPC-{100000 + index}",
        license_type="LPC",
        license_status="Active",
        license_issue_date=license_issue,
        license_expiration_date=license_expiration,
        issuing_board="Texas Behavioral Health Executive Council",
        license_holder_name=legal_name,
        coi_carrier=f"{fake.company()} Mutual Insurance",
        coi_policy_number=f"POL-{200000 + index}",
        coi_effective_date=coi_effective,
        coi_expiration_date=coi_expiration,
        coi_per_occurrence=100_000,
        coi_aggregate=300_000,
        coi_insured_name=legal_name,
        positions=positions,
        education_institution=f"University of {fake.city()}",
        education_degree="M.A. Counseling Psychology",
        education_date=license_issue - timedelta(days=200),
        w9_business_name=practice_name,
        w9_tin=w9_tin,
    )
