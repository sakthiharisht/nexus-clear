from __future__ import annotations

import json

import httpx
import pytest

from app.backends.jev_backend import JevBackend, _legible_from_score_answer
from app.backends.types import ClassifyInput
from app.core.redact import SSN_MASK


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.typesafe.ai")


def _fake_response_body(**overrides: object) -> dict[str, object]:
    # Shape confirmed against the real live API (M5.1, 2026-11-04) -
    # see jev_backend.py's module docstring.
    body: dict[str, object] = {
        "model": "jev-1.14.0",
        "answers": {
            "doc_type": {
                "type": "choice",
                "choice": "cv",
                "confidence": 1.0,
                "probabilities": {"cv": 0.9, "other": 0.1},
            },
            "legible": {
                "type": "score",
                "score": 3.0,  # index 3 of 5 levels -> 3/4 = 0.75
                "confidence": 0.9,
                "legend": {
                    "0": "illegible",
                    "1": "poor",
                    "2": "fair",
                    "3": "good",
                    "4": "excellent",
                },
                "probabilities": {"0": 0.0, "1": 0.0, "2": 0.05, "3": 0.9, "4": 0.05},
            },
            "slot_match": {"type": "noul", "noul": 0.8},
        },
        "usage": {"input_tokens": 311, "output_tokens": 21},
    }
    body.update(overrides)
    return body


def test_classify_sends_the_pinned_model_and_parses_the_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_fake_response_body())

    backend = JevBackend(api_key="test-key", model="jev-1.14.0", client=_client(handler))
    result = backend.classify(
        ClassifyInput(slot="cv", filename="resume.pdf", allowed_doc_types=["cv", "other"])
    )

    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "jev-1.14.0"

    assert result.doc_type == "cv"
    assert result.probabilities == {"cv": 0.9, "other": 0.1}
    assert result.legible == pytest.approx(0.75)
    assert result.slot_match is True
    assert result.decided_by == "jev"
    assert result.input_tokens == 311
    assert result.output_tokens == 21
    # Jev's direct-API pricing isn't verified (see module docstring) -
    # cost is deliberately 0.0, not a guessed number.
    assert result.cost_usd == 0.0


def test_request_sends_criteria_as_a_dict_for_choice_and_a_list_for_score() -> None:
    """The real API 422s on the reverse of either (confirmed live,
    M5.1): `choice.criteria` must be a dict (option -> description),
    `score.criteria` must be a list of ordered labels."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_fake_response_body())

    backend = JevBackend(api_key="test-key", model="jev-1.14.0", client=_client(handler))
    backend.classify(ClassifyInput(slot="cv", filename="resume.pdf", allowed_doc_types=["cv"]))

    questions = captured["body"]["questions"]  # type: ignore[index]
    assert isinstance(questions["doc_type"]["criteria"], dict)
    assert isinstance(questions["legible"]["criteria"], list)
    assert "instructions" in questions["slot_match"]


def test_classify_raises_on_a_non_2xx_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    backend = JevBackend(api_key="wrong", model="jev-1.14.0", client=_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        backend.classify(
            ClassifyInput(slot="cv", filename="resume.pdf", allowed_doc_types=["cv"])
        )


def test_classify_redacts_ssn_shaped_text_out_of_the_request_state() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_fake_response_body())

    backend = JevBackend(api_key="test-key", model="jev-1.14.0", client=_client(handler))
    backend.classify(
        ClassifyInput(
            slot="w9",
            filename="w9.pdf",
            allowed_doc_types=["w9"],
            page1_text="TIN: 000-02-1002 (synthetic, clearly-invalid format)",
        )
    )

    body = captured["body"]
    assert isinstance(body, dict)
    serialized_state = json.dumps(body["state"])
    assert "000-02-1002" not in serialized_state
    assert SSN_MASK in serialized_state


def test_classify_attaches_an_image_block_when_an_image_is_provided() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_fake_response_body())

    backend = JevBackend(api_key="test-key", model="jev-1.14.0", client=_client(handler))
    backend.classify(
        ClassifyInput(
            slot="license",
            filename="license.png",
            allowed_doc_types=["texas_lpc_license"],
            page1_image_b64="Zm9v",
            page1_image_media_type="image/png",
        )
    )

    body = captured["body"]
    assert isinstance(body, dict)
    state = body["state"]
    assert isinstance(state, list)
    image_blocks = [s for s in state if isinstance(s, dict) and s.get("type") == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"] == "data:image/png;base64,Zm9v"


def test_legible_from_score_answer_normalizes_the_raw_index() -> None:
    # index 4 of 5 levels (illegible=0 .. excellent=4) -> 4/4 = 1.0
    assert _legible_from_score_answer({"score": 4.0}) == 1.0


def test_legible_from_score_answer_handles_a_fractional_score() -> None:
    # the real API returns fractional positions, e.g. 3.95 - confirmed live.
    assert _legible_from_score_answer({"score": 3.95}) == pytest.approx(3.95 / 4)
