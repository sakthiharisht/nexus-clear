from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.backends.claude_extractor import ClaudeExtractor
from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    CvPositionExtraction,
    ExtractedField,
    ExtractInput,
    LicenseExtraction,
)
from app.core.redact import SSN_MASK


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeParsedMessage:
    parsed_output: Any
    usage: _FakeUsage
    stop_reason: str = "end_turn"


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


def test_extract_maps_parsed_output_into_an_extraction_result() -> None:
    parsed = LicenseExtraction(
        holder_name=ExtractedField(
            value="Jane Doe", confidence=0.95, page=1, quote="Holder name: Jane Doe"
        )
    )
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(100, 50)))
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    result = extractor.extract(
        ExtractInput(
            doc_id="doc-license",
            kind="license",
            filename="license.pdf",
            document_text="Holder name: Jane Doe",
        )
    )

    assert result.kind == "license"
    assert isinstance(result.fields, LicenseExtraction)
    assert result.fields.holder_name.value == "Jane Doe"
    assert result.decided_by == "claude"
    assert result.cost_usd > 0
    assert result.cost_known is True
    assert result.latency_ms >= 0


def test_extract_raises_if_claude_returns_no_parsed_output() -> None:
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=None, usage=_FakeUsage(10, 10)))
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="parsed structured output"):
        extractor.extract(
            ExtractInput(doc_id="doc-1", kind="coi", filename="coi.pdf", document_text="text")
        )


def test_extract_returns_unknown_with_reason_when_stop_reason_is_max_tokens() -> None:
    """M6.1: a response cut off by max_tokens must become an
    unknown-with-reason ExtractionResult, never a raised exception -
    one bad document's garbled output must not crash a batch run."""
    fake_client = _FakeClient(
        _FakeParsedMessage(
            parsed_output=None, usage=_FakeUsage(500, 2048), stop_reason="max_tokens"
        )
    )
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    result = extractor.extract(
        ExtractInput(doc_id="doc-1", kind="license", filename="license.pdf", document_text="text")
    )

    assert result.extraction_error is not None
    assert "max_tokens" in result.extraction_error
    assert isinstance(result.fields, LicenseExtraction)
    assert result.fields.holder_name.value is None


def test_extract_treats_max_tokens_as_unreliable_even_if_it_happened_to_parse() -> None:
    """stop_reason == "max_tokens" is checked unconditionally, even
    when parsed_output is (surprisingly) non-None - a truncated
    response is never trustworthy enough to treat as complete."""
    parsed = LicenseExtraction(
        holder_name=ExtractedField(value="Jane Doe", confidence=0.9, page=1, quote="Jane Doe")
    )
    fake_client = _FakeClient(
        _FakeParsedMessage(
            parsed_output=parsed, usage=_FakeUsage(500, 2048), stop_reason="max_tokens"
        )
    )
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    result = extractor.extract(
        ExtractInput(doc_id="doc-1", kind="license", filename="license.pdf", document_text="text")
    )

    assert result.extraction_error is not None
    assert isinstance(result.fields, LicenseExtraction)
    assert result.fields.holder_name.value is None  # discarded, not the parsed value


def test_extract_returns_unknown_with_reason_on_a_validation_error() -> None:
    """M6.1: the SDK raises pydantic.ValidationError directly (no
    response object at all) when the model's text content isn't valid
    JSON - in practice, truncated mid-object. Must also become
    unknown-with-reason, not propagate."""

    class _DummyModel(BaseModel):
        value: int

    try:
        _DummyModel.model_validate_json('{"value": "not-an-int-and-truncat')
        pytest.fail("expected a real pydantic.ValidationError to construct this fixture")
    except ValidationError as real_validation_error:
        captured_error = real_validation_error

    class _RaisingMessagesAPI:
        def parse(self, **kwargs: Any) -> Any:
            raise captured_error

    class _RaisingClient:
        messages = _RaisingMessagesAPI()

    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=_RaisingClient())  # type: ignore[arg-type]

    result = extractor.extract(
        ExtractInput(doc_id="doc-1", kind="coi", filename="coi.pdf", document_text="text")
    )

    assert result.extraction_error is not None
    assert "failed to parse" in result.extraction_error
    assert isinstance(result.fields, CoiExtraction)
    assert result.fields.insured_name.value is None
    # No response object ever came back - usage/cost are genuinely
    # unknown for this call, not a measured zero.
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_extract_uses_the_schema_matching_the_requested_kind() -> None:
    parsed = CoiExtraction()
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(10, 10)))
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    extractor.extract(
        ExtractInput(doc_id="doc-1", kind="coi", filename="coi.pdf", document_text="text")
    )

    sent = fake_client.messages.last_kwargs
    assert sent is not None
    assert sent["output_format"] is CoiExtraction


def test_extract_attaches_an_image_block_when_an_image_is_provided() -> None:
    parsed = LicenseExtraction()
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(10, 10)))
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    extractor.extract(
        ExtractInput(
            doc_id="doc-license",
            kind="license",
            filename="license.png",
            image_b64="Zm9v",
            image_media_type="image/png",
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


def test_extract_redacts_ssn_shaped_text_out_of_the_prompt_sent_to_claude() -> None:
    parsed = LicenseExtraction()
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(10, 10)))
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    extractor.extract(
        ExtractInput(
            doc_id="doc-1",
            kind="w9",
            filename="w9.pdf",
            document_text="TIN: 000-02-1002 (synthetic, clearly-invalid format)",
        )
    )

    sent = fake_client.messages.last_kwargs
    assert sent is not None
    prompt = sent["messages"][0]["content"]
    assert SSN_MASK in prompt
    assert "000-02-1002" not in prompt


def test_extract_cv_schema_round_trips_positions() -> None:
    parsed = CvExtraction(
        name=ExtractedField(value="Jane Doe", confidence=0.9, page=1, quote="Name: Jane Doe"),
        positions=[
            CvPositionExtraction(
                title=ExtractedField(value="Counselor", confidence=0.9, page=1, quote="Counselor")
            )
        ],
    )
    fake_client = _FakeClient(_FakeParsedMessage(parsed_output=parsed, usage=_FakeUsage(10, 10)))
    extractor = ClaudeExtractor(model="claude-haiku-5-5", client=fake_client)  # type: ignore[arg-type]

    result = extractor.extract(
        ExtractInput(doc_id="doc-cv", kind="cv", filename="cv.pdf", document_text="Name: Jane Doe")
    )

    assert isinstance(result.fields, CvExtraction)
    assert result.fields.positions[0].title.value == "Counselor"
