"""Core cross-stage contract (SPEC.md section 4).

Every pipeline stage speaks these types at its boundary (CLAUDE.md: "Pydantic
models at every stage boundary"). In particular, `Finding.status` for a
date/numeric/enum/presence rule is set by the rules engine (app/rules/engine.py)
— never by a model (CLAUDE.md invariant 1) — and every `Finding` the engine
emits carries `evidence` and `rule_source` so a reviewer can trace *why*
(CLAUDE.md invariant 2).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EvidenceKind = Literal["document", "registry"]
FindingStatus = Literal["pass", "fail", "not_applicable", "unknown"]
Severity = Literal["blocker", "warning", "info"]
DecidedBy = Literal["code", "jev", "claude", "human"]


class EvidenceRef(BaseModel):
    """A pointer to the one document quote or registry record that backs a
    Finding. `kind` selects which half of the union is populated; the other
    half's fields stay `None` rather than being omitted, so every EvidenceRef
    has a stable shape regardless of kind.
    """

    kind: EvidenceKind

    # kind == "document"
    doc_id: str | None = None
    page: int | None = None
    quote: str | None = None

    # kind == "registry"
    registry: str | None = None
    record_hash: str | None = None
    fetched_at: datetime | None = None


class RuleSource(BaseModel):
    """Provenance for the rule that produced a Finding — where it came from,
    whether it was independently confirmed, and when. Mirrors the `sources`
    entries in a rule pack (rules/tx_bcbstx_lpc.yaml); see app/rules/schema.py.
    """

    source_id: str
    url: str | None = None
    doc_date: str | None = None
    last_verified: str
    needs_verification: bool


class Finding(BaseModel):
    """The output unit of the Validate stage (and later Reconcile/Escalate):
    one rule, evaluated, with evidence and provenance attached. `confidence`
    is only set when a model contributed to the decision (name_match /
    registry_check kinds once Reconcile exists); pure code-decided kinds
    leave it `None`.
    """

    finding_id: str
    rule_id: str
    status: FindingStatus
    severity: Severity
    evidence: list[EvidenceRef]
    rule_source: RuleSource
    confidence: float | None = None
    decided_by: DecidedBy
