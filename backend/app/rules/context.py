"""CaseFacts: the typed input the rules engine evaluates (SPEC.md section 7.4).

M1 scope boundary: this is NOT the final Extraction contract (SPEC.md section
7.3 — value/confidence/page/quote per field, built in M6). It's the engine's
own typed view of "whatever is known about this case right now," simple
enough to construct by hand in tests without the Intake/Classify/Extract
stages existing yet. `None` here means "we don't have this value" — on its
own that's ambiguous between "not yet extracted" and "extraction ran and
found nothing." `DocumentFact.readable` (see `is_slot_readable`) resolves
that ambiguity for kinds that need it: a rule reading a value from an
unreadable document reports `unknown`, and only reports a confirmed-absent
`fail` when the document was actually read. Most kinds never need this —
a single missing field is already `unknown` to them regardless of why —
but `presence_all` does, since its whole job is judging presence/absence.

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
    # Intake-provided (like profile.*), not document-extracted: the
    # Associate's application names their supervisor's license number.
    # Used as the tx_license_lookup key for R-SUP-001 (see
    # app/eval/baseline_reconcile.py); no rule reads it directly.
    supervisor_license_number: str | None = None


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

    `readable` distinguishes "this document was processed and a field came
    back blank" from "this document couldn't be processed at all" (e.g. a
    scanned image with no text layer, or classification failure) — see
    `is_slot_readable` and CLAUDE.md invariant 2: a field with no supporting
    evidence is `unknown`, never guessed. Defaults to True because most
    CaseFacts in this codebase are hand-built ground truth (M1/M2 tests,
    CEILING mode) where "was it readable" isn't a meaningful question — only
    a real extractor (app/eval/baseline_extraction.py) sets it to False.
    """

    doc_id: str
    slot: str
    expected_doc_type: str | None = None
    uploaded_doc_type: str | None = None
    legible_score: float | None = None
    contains_injection_text: bool | None = None
    readable: bool = True


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


def is_slot_readable(facts: CaseFacts, slot: str) -> bool:
    """Was the document at this slot actually processed? Used by kinds that
    need to tell "confirmed absent" (fail) apart from "we don't know"
    (unknown) when a field is missing — see DocumentFact.readable.

    Defaults to True when there's no matching DocumentFact: namespaces that
    aren't document-backed at all (profile, supervision) should never be
    treated as "unreadable", and CaseFacts built without an explicit
    documents list (most hand-built ground truth) shouldn't either.
    """
    for doc in facts.documents:
        if doc.slot == slot:
            return doc.readable
    return True
