"""SPEC.md section 7.2: "Backend protocol `DecisionBackend` with
`JevBackend` and `ClaudeBackend`; chosen per call by config."
"""

from __future__ import annotations

from typing import Protocol

from app.backends.types import ClassificationResult, ClassifyInput


class DecisionBackend(Protocol):
    @property
    def name(self) -> str:  # "jev" | "claude" - cache keys, logging, decided_by
        ...

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult: ...
