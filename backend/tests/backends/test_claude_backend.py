from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.backends.claude_backend import ClaudeBackend, _ClaudeClassification, _estimate_cost_usd
from app.backends.types import ClassifyInput
from app.core.redact import SSN_MASK


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeParsedMessage:
    parsed_output: Any
    usage: _FakeUsage


class _FakeMessagesAPI:
    def __init__(self, response: _FakeParsedMessage) -> None:
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    def parse(self, **kwargs: Any) -> _FakeParsedMessage:
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response: _FakeParsedMessage) -> None:
        self.messages = _FakeMessagesAPI(response)


def test_estimate_cost_usd_uses_the_pinned_models_rate() -> None:
    cost = _estimate_cost_usd("claude-haiku-5-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.10 + 0.50


def test_estimate_cost_usd_is_zero_for_an_unpinned_model() -> None:
    assert _estimate_cost_usd("some-unknown-model", input_tokens=1000, output_tokens=1000) == 0.0


def test_classify_maps_parsed_output_into_a_classification_result() -> None:
    parsed = _ClaudeClassification(
        doc_type="cv", doc_type_confidence=0.92, legible=0.95, slot_match=False
    )
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(100, 50)))
    backend = ClaudeBackend(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    result = backend.classify(
        ClassifyInput(slot="license", filename="x.pdf", allowed_doc_types=["cv", "other"])
    )

    assert result.doc_type == "cv"
    assert result.probabilities == {"cv": 0.92}
    assert result.legible == 0.95
    assert result.slot_match is False
    assert result.decided_by == "claude"
    assert result.cost_usd > 0
    assert result.latency_ms >= 0


def test_classify_raises_if_claude_returns_no_parsed_output() -> None:
    import pytest

    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=None, usage=_FakeUsage(10, 10)))
    backend = ClaudeBackend(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="parsed structured output"):
        backend.classify(
            ClassifyInput(slot="license", filename="x.pdf", allowed_doc_types=["cv"])
        )


def test_classify_attaches_an_image_block_when_an_image_is_provided() -> None:
    parsed = _ClaudeClassification(
        doc_type="texas_lpc_license",
        doc_type_confidence=0.9,
        legible=0.9,
        slot_match=True,
    )
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(10, 10)))
    backend = ClaudeBackend(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    backend.classify(
        ClassifyInput(
            slot="license",
            filename="license.png",
            allowed_doc_types=["texas_lpc_license"],
            page1_image_b64="Zm9v",
            page1_image_media_type="image/png",
        )
    )

    sent = fake_client.messages.last_kwargs
    assert sent is not None
    content = sent["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "Zm9v"},
    }


def test_classify_redacts_ssn_shaped_text_out_of_the_prompt_sent_to_claude() -> None:
    parsed = _ClaudeClassification(
        doc_type="w9", doc_type_confidence=0.9, legible=0.9, slot_match=True
    )
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(10, 10)))
    backend = ClaudeBackend(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    backend.classify(
        ClassifyInput(
            slot="w9",
            filename="w9.pdf",
            allowed_doc_types=["w9"],
            page1_text="TIN: 000-02-1002 (synthetic, clearly-invalid format)",
        )
    )

    sent = fake_client.messages.last_kwargs
    assert sent is not None
    content = sent["messages"][0]["content"]
    assert "000-02-1002" not in content
    assert SSN_MASK in content
