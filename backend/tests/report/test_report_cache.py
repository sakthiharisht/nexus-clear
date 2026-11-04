from __future__ import annotations

from pathlib import Path

import pytest

from app.report.cache import CachedPhraser, MissingFixtureError, cache_key
from app.report.types import PhraseRequest, PhraseResult


class _FakePhraser:
    name = "fake"
    prompt_version = "test"

    def __init__(self) -> None:
        self.calls = 0

    def phrase(self, requests: list[PhraseRequest]) -> PhraseResult:
        self.calls += 1
        return PhraseResult(sentences={r.finding_id: "phrased" for r in requests})


def _requests(finding_id: str = "R-LIC-002") -> list[PhraseRequest]:
    return [
        PhraseRequest(
            finding_id=finding_id, rule_title="x", status="fail", evidence_quotes=["a quote"]
        )
    ]


def test_cache_key_is_deterministic_for_the_same_input() -> None:
    assert cache_key("claude", "model-x", "v1", _requests()) == cache_key(
        "claude", "model-x", "v1", _requests()
    )


def test_cache_key_differs_for_different_requests() -> None:
    assert cache_key("claude", "model-x", "v1", _requests("R-A")) != cache_key(
        "claude", "model-x", "v1", _requests("R-B")
    )


def test_cache_key_differs_for_different_prompt_versions() -> None:
    assert cache_key("claude", "model-x", "v1", _requests()) != cache_key(
        "claude", "model-x", "v2", _requests()
    )


def test_replay_mode_raises_on_a_cache_miss(tmp_path: Path) -> None:
    fake = _FakePhraser()
    cached = CachedPhraser(fake, model="model-x", cache_root=tmp_path, mode="replay")
    with pytest.raises(MissingFixtureError):
        cached.phrase(_requests())
    assert fake.calls == 0


def test_an_empty_request_list_never_hits_the_cache_or_backend(tmp_path: Path) -> None:
    fake = _FakePhraser()
    cached = CachedPhraser(fake, model="model-x", cache_root=tmp_path, mode="replay")
    result = cached.phrase([])
    assert result.sentences == {}
    assert fake.calls == 0


def test_record_mode_calls_the_backend_and_writes_the_cache(tmp_path: Path) -> None:
    fake = _FakePhraser()
    cached = CachedPhraser(fake, model="model-x", cache_root=tmp_path, mode="record")
    result = cached.phrase(_requests())
    assert result.sentences == {"R-LIC-002": "phrased"}
    assert fake.calls == 1
    assert list(tmp_path.glob("fake/*.json"))


def test_a_cache_hit_never_calls_the_backend_again(tmp_path: Path) -> None:
    fake = _FakePhraser()
    cached = CachedPhraser(fake, model="model-x", cache_root=tmp_path, mode="record")
    cached.phrase(_requests())
    assert fake.calls == 1

    replay_cached = CachedPhraser(
        _FakePhraser(), model="model-x", cache_root=tmp_path, mode="replay"
    )
    result = replay_cached.phrase(_requests())
    assert result.sentences == {"R-LIC-002": "phrased"}
