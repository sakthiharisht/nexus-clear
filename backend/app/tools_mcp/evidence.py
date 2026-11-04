"""EvidenceRecord (SPEC.md section 7.6): the typed result every MCP
tool returns, regardless of mode. `record_hash` is a hash of `payload`
alone (not `fetched_at`) - it identifies what the data SAYS, so the
same query returning the same content twice produces the same hash
even if the clock moved, and a genuinely different answer (the
registry record changed) produces a different one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

RegistrySource = Literal["nppes", "tx_license", "leie", "rule_pack"]


def compute_record_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class EvidenceRecord(BaseModel):
    source: RegistrySource
    query: str
    fetched_at: datetime
    record_hash: str
    payload: dict[str, Any]
    # Not in SPEC 7.6's literal (source, query, fetched_at, record_hash,
    # payload) list, but necessary: a reviewer or the Investigator
    # reading this record needs to know whether it came from a
    # committed fixture or a real registry call - the same reason
    # app/backends/types.py's ClassificationResult carries `simulated`.
    mode: Literal["fixture", "live"]


def make_evidence_record(
    source: RegistrySource, query: str, payload: dict[str, Any], *, mode: Literal["fixture", "live"]
) -> EvidenceRecord:
    return EvidenceRecord(
        source=source,
        query=query,
        fetched_at=datetime.now().astimezone(),
        record_hash=compute_record_hash(payload),
        payload=payload,
        mode=mode,
    )
