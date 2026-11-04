"""Gap report phraser stage boundary (SPEC.md section 7.8): the typed
input/output around any backend that turns a Finding's evidence into a
plain-English sentence. Parallel to app/backends/base.py's
DecisionBackend and app/reconcile/investigator.py's InvestigatorLike -
same shape, a different job.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class PhraseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str
    rule_title: str
    status: str
    evidence_quotes: list[str]


class PhraseResult(BaseModel):
    # finding_id -> sentence. Only finding_ids the phraser actually
    # returned a sentence for - app/report/gap_report.py falls back to
    # a deterministic template for anything missing, same as a sentence
    # that fails verification.
    sentences: dict[str, str] = {}
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True
    latency_ms: float = 0.0
    simulated: bool = False


class SentencePhraser(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...  # M7 housekeeping #1 - app/core/prompt_version.py

    def phrase(self, requests: list[PhraseRequest]) -> PhraseResult: ...
