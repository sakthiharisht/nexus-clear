"""SQLAlchemy ORM models for the case store (SPEC.md section 5).

These are storage models only — the API/pipeline boundary types are the
Pydantic contracts in app/core/contracts.py (SPEC.md section 4). Nothing here
encodes business logic; rows are read/written by the stages as they land in
later milestones.

Enum-like columns (state, status, actor, decided_by, stage) are plain String
columns rather than native Postgres enums, to keep Alembic migrations simple
in the skeleton; validity is enforced at the Pydantic boundary before a row
is ever written.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_profile: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payer: Mapped[str] = mapped_column(String, nullable=False)
    provider_type: Mapped[str] = mapped_column(String, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    # One of: created, documents_uploaded, extracted, validated, reconciled,
    # reported, in_review, ready, attested (SPEC.md section 5).
    state: Mapped[str] = mapped_column(String, nullable=False, default="created")
    # Envelope encryption (SPEC.md section 7.1): this case's own data
    # encryption key, generated once and wrapped under the KeyManager's
    # master key (app/vault/key_manager.py) — never stored unwrapped.
    wrapped_data_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Human gate (SPEC.md section 7.9, M8): set together, exactly once,
    # by the attest endpoint - never by any code path acting on the
    # provider's behalf (CLAUDE.md invariant 5). `attested_packet` is a
    # full snapshot (not just the hash) so a later re-run's fresh
    # Extraction rows can never change what GET /cases/{id}/packet
    # returns for an already-attested case - the hash it was attested
    # under must stay independently verifiable forever. Kept here, not
    # in audit_log.detail, because audit_log must never carry
    # extracted PII (CLAUDE.md invariant 4) and this packet does.
    attested_by: Mapped[str | None] = mapped_column(String, nullable=True)
    attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attested_packet: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    attested_packet_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # SPEC.md section 7.1: "Duplicate hash in same case -> reject as
        # duplicate" — enforced at the API layer (app/api/cases.py) for a
        # clean error message, and here as a DB-level backstop.
        UniqueConstraint("case_id", "sha256", name="uq_documents_case_sha256"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    slot: Mapped[str] = mapped_column(String, nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which KeyManager/scheme wrapped this case's data key (e.g.
    # "local-v1") — metadata for future key rotation, not key material
    # itself (that's cases.wrapped_data_key, one per case).
    key_id: Mapped[str] = mapped_column(String, nullable=False)
    storage_ref: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    classification: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    fields: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FindingRecord(Base):
    """Persisted Finding rows. Column name is `finding` per SPEC.md section 5;
    the class is `FindingRecord` to avoid clashing with the Pydantic `Finding`
    contract in app/core/contracts.py.
    """

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    rule_pack_version: Mapped[str] = mapped_column(String, nullable=False)
    finding: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("findings.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    reviewer_resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Append-only. Application code must never UPDATE or DELETE a row here,
    and must never write document text, extracted PII, or secrets into
    `detail` (CLAUDE.md invariant 4).
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    object_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    # One of: code, jev, claude, human (matches Finding.decided_by).
    decided_by: Mapped[str] = mapped_column(String, nullable=False)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
