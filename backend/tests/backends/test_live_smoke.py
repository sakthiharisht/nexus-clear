"""Opt-in smoke tests against the REAL Claude/Jev APIs. Skipped
automatically whenever the relevant key is absent from the
environment - which is always true in CI (no secrets configured there)
and true locally unless backend/.env has been filled in. Never
mark/xfail these to force them to run in CI; the skip condition is the
intended gate, not a workaround.

These make a small, fixed number of real, billed calls - not the full
60-document batch (that's app/eval/live_classify.py, invoked
explicitly, never from pytest).
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from app.backends.claude_backend import ClaudeBackend
from app.backends.jev_backend import JevBackend
from app.backends.types import ClassifyInput

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_HAS_ANTHROPIC_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
_HAS_JEV_KEY = bool(os.environ.get("JEV_API_KEY"))

_SAMPLE_TEXT = "Curriculum Vitae\n\nJohn Smith, LPC\nExperience: ...\n"


@pytest.mark.skipif(not _HAS_ANTHROPIC_KEY, reason="no ANTHROPIC_API_KEY in backend/.env")
def test_claude_haiku_classifies_a_real_document_live() -> None:
    backend = ClaudeBackend(model="claude-haiku-5-5")
    result = backend.classify(
        ClassifyInput(
            slot="cv",
            filename="smoke-test-cv.pdf",
            allowed_doc_types=["texas_lpc_license", "malpractice_coi", "cv", "w9", "other"],
            page1_text=_SAMPLE_TEXT,
        )
    )
    assert result.doc_type in {"texas_lpc_license", "malpractice_coi", "cv", "w9", "other"}
    assert 0.0 <= result.legible <= 1.0
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert result.cost_usd > 0.0
    assert result.decided_by == "claude"
    assert result.simulated is False


@pytest.mark.skipif(not _HAS_JEV_KEY, reason="no JEV_API_KEY in backend/.env")
def test_jev_classifies_a_real_document_live() -> None:
    backend = JevBackend(api_key=os.environ["JEV_API_KEY"], model="jev-1.14.0")
    result = backend.classify(
        ClassifyInput(
            slot="cv",
            filename="smoke-test-cv.pdf",
            allowed_doc_types=["texas_lpc_license", "malpractice_coi", "cv", "w9", "other"],
            page1_text=_SAMPLE_TEXT,
        )
    )
    assert result.doc_type in {"texas_lpc_license", "malpractice_coi", "cv", "w9", "other"}
    assert 0.0 <= result.legible <= 1.0
    assert result.input_tokens > 0
    assert result.decided_by == "jev"
    assert result.simulated is False
