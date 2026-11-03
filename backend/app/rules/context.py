"""CaseFacts: the typed input the rules engine evaluates (SPEC.md section 7.4).

M1 scope boundary: this is NOT the final Extraction contract (SPEC.md section
7.3 — value/confidence/page/quote per field, built in M6). It's the engine's
own typed view of "whatever is known about this case right now," simple
enough to construct by hand in tests without the Intake/Classify/Extract
stages existing yet. `None` here means "we don't have this value" — it does
not distinguish "not yet extracted" from "extraction ran and found nothing,"
which the real Extraction contract will. Rule kinds that treat a missing
value as `unknown` rather than `fail` do so because of this collapse.

Two fields are deliberately pre-resolved rather than computed by this
engine: `name_match_probabilities` and `registry_results`. SPEC.md section
4's stage order is Validate (this module) before Reconcile (section 7.5,
where name fuzzy-matching and MCP registry calls actually happen — M5/M7).
A `name_match` or `registry_check` rule here can only threshold a result
that's already been resolved upstream; if it hasn't been (dict has no entry
for the rule id), the rule evaluates to `unknown`. This is flagged as a
SPEC.md change proposal in the M1 completion report, not assumed silently.
"""

from datetime import date, datetime

from pydantic import BaseModel


class LicenseFacts(BaseModel):
    doc_id: str | None = None
    holder_name: str | None = None
    license_number: str | None = None
    license_type: str | None = None
    status: str | None = None
    issue_date: date | None = None
    expiration_date: date | None = None
    issuing_board: str | None = None


class CoiFacts(BaseModel):
    doc_id: str | None = None
    insured_name: str | None = None
    carrier: str | None = None
    policy_number: str | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    per_occurrence: float | None = None
    aggregate: float | None = None


class CvPosition(BaseModel):
    title: str | None = None
    employer: str | None = None
    start: date | None = None
    end: date | None = None  # None means "ongoing as of target_date"


class CvFacts(BaseModel):
    doc_id: str | None = None
    positions: list[CvPosition] = []


class ProfileFacts(BaseModel):
    legal_name: str | None = None
    practice_name: str | None = None
    npi: str | None = None


class SupervisionFacts(BaseModel):
    supervisor_count: int | None = None


class RegistryResult(BaseModel):
    """A pre-resolved MCP tool result (SPEC.md section 7.6), keyed by rule id
    in CaseFacts.registry_results. Shape is a superset of what any single
    registry_check rule needs — see app/rules/kinds.py for which fields a
    given rule's params actually read."""

    exists: bool | None = None
    status: str | None = None
    checks: dict[str, bool] = {}
    possible_match: bool | None = None
    registry: str | None = None
    record_hash: str | None = None
    fetched_at: datetime | None = None


class DocumentFact(BaseModel):
    """One uploaded document, for the three per-document rule kinds
    (doc_type_match, legibility, injection_flag — see app/rules/engine.py).
    Unlike the other *Facts models, a rule of one of these kinds produces one
    Finding per DocumentFact, not one Finding total.
    """

    doc_id: str
    slot: str
    expected_doc_type: str | None = None
    uploaded_doc_type: str | None = None
    legible_score: float | None = None
    contains_injection_text: bool | None = None


class CaseFacts(BaseModel):
    target_date: date
    license: LicenseFacts = LicenseFacts()
    coi: CoiFacts = CoiFacts()
    cv: CvFacts = CvFacts()
    profile: ProfileFacts = ProfileFacts()
    supervision: SupervisionFacts = SupervisionFacts()
    documents: list[DocumentFact] = []

    name_match_probabilities: dict[str, float] = {}
    registry_results: dict[str, RegistryResult] = {}


def get_path(facts: CaseFacts, path: str) -> object | None:
    """Resolve a dotted field path (e.g. "license.expiration_date") against
    CaseFacts. Returns None if any segment along the way is missing — a rule
    referencing a field that isn't there evaluates to `unknown`, not a crash.
    """
    obj: object = facts
    for part in path.split("."):
        obj = getattr(obj, part, None)
    return obj
