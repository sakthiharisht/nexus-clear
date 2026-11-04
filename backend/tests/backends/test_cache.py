from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.cache import CachedBackend, MissingFixtureError, cache_key
from app.backends.types import ClassificationResult, ClassifyInput


class _FakeBackend:
    name = "fake"
    prompt_version = "test"

    def __init__(self) -> None:
        self.calls = 0

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
        self.calls += 1
        return ClassificationResult(
            doc_type="cv",
            probabilities={"cv": 0.99},
            legible=0.9,
            slot_match=True,
            decided_by="claude",
        )


def _input(slot: str = "cv") -> ClassifyInput:
    return ClassifyInput(
        slot=slot,
        filename="x.pdf",
        allowed_doc_types=["cv", "other"],
        page1_text="some text",
    )


def test_cache_key_is_deterministic_for_the_same_input() -> None:
    assert cache_key("claude", "model-x", "v1", _input()) == cache_key(
        "claude", "model-x", "v1", _input()
    )


def test_cache_key_differs_for_different_inputs() -> None:
    assert cache_key("claude", "model-x", "v1", _input("cv")) != cache_key(
        "claude", "model-x", "v1", _input("license")
    )


def test_cache_key_differs_for_different_prompt_versions() -> None:
    """M7 housekeeping #1: an edited prompt must change the key even
    when the model and input are identical, so a stale fixture can
    never silently replay output recorded under a different prompt."""
    assert cache_key("claude", "model-x", "v1", _input()) != cache_key(
        "claude", "model-x", "v2", _input()
    )


def test_replay_mode_raises_on_a_cache_miss(tmp_path: Path) -> None:
    fake = _FakeBackend()
    cached = CachedBackend(fake, model="model-x", cache_root=tmp_path, mode="replay")
    with pytest.raises(MissingFixtureError):
        cached.classify(_input())
    assert fake.calls == 0  # never falls back to a live call


def test_record_mode_calls_the_backend_and_writes_the_cache(tmp_path: Path) -> None:
    fake = _FakeBackend()
    cached = CachedBackend(fake, model="model-x", cache_root=tmp_path, mode="record")
    result = cached.classify(_input())
    assert result.doc_type == "cv"
    assert fake.calls == 1
    assert list(tmp_path.glob("fake/*.json"))


def test_a_cache_hit_never_calls_the_backend_again(tmp_path: Path) -> None:
    fake = _FakeBackend()
    cached = CachedBackend(fake, model="model-x", cache_root=tmp_path, mode="record")
    cached.classify(_input())
    assert fake.calls == 1

    # Same input, fresh instance pointed at the same cache root - a
    # hit, even in replay mode which would otherwise raise.
    replay_cached = CachedBackend(
        _FakeBackend(), model="model-x", cache_root=tmp_path, mode="replay"
    )
    result = replay_cached.classify(_input())
    assert result.doc_type == "cv"


def test_cache_name_property_delegates_to_the_wrapped_backend(tmp_path: Path) -> None:
    cached = CachedBackend(_FakeBackend(), model="model-x", cache_root=tmp_path, mode="replay")
    assert cached.name == "fake"
