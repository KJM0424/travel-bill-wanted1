from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

from core.recognizer import RecognitionError
from core.recognizer.gemini import HTTP_TIMEOUT_MS, GeminiRecognizer

FIXTURES = Path(__file__).parent / "fixtures" / "receipts"
food_json = (FIXTURES / "food.json").read_text(encoding="utf-8")


class FakeModels:
    def __init__(self, responses: list, calls: list):
        self._responses = list(responses)
        self._calls = calls

    def generate_content(self, *, model, contents, config):
        self._calls.append({"model": model, "contents": contents, "config": config})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fake_client(responses: list):
    calls: list = []
    return SimpleNamespace(models=FakeModels(responses, calls), calls=calls)


def ok_text(text: str):
    return SimpleNamespace(text=text)


def rate_limit_error():
    return errors.APIError(
        429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )


def server_error():
    return errors.APIError(
        500, {"error": {"code": 500, "message": "internal", "status": "INTERNAL"}}
    )


def test_returns_parsed_receipt():
    r = GeminiRecognizer("k", client=fake_client([ok_text(food_json)]), sleep=lambda s: None)
    assert r.recognize(b"img", "v1").total_amount == 96000


def test_sends_schema_and_prompt():
    client = fake_client([ok_text(food_json)])
    GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    call = client.calls[0]
    assert call["config"].response_mime_type == "application/json"
    assert any("실제 결제" in str(p) for p in call["contents"])


def test_retries_on_rate_limit_then_succeeds():
    sleeps = []
    client = fake_client([rate_limit_error(), rate_limit_error(), ok_text(food_json)])
    GeminiRecognizer("k", client=client, sleep=sleeps.append).recognize(b"img", "v1")
    assert sleeps == [1, 2]


def test_gives_up_after_rate_limit_retries():
    client = fake_client([rate_limit_error()] * 4)
    with pytest.raises(RecognitionError, match="한도"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 4


def test_retries_once_on_invalid_json_then_fails():
    client = fake_client([ok_text("{not json"), ok_text('{"doc_type": "?"}')])
    with pytest.raises(RecognitionError, match="형식"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 2


def test_other_api_error_is_wrapped_without_key():
    leaking = errors.APIError(
        400, {"error": {"code": 400, "message": "bad key secret-key-123", "status": "INVALID"}}
    )
    client = fake_client([leaking])
    with pytest.raises(RecognitionError, match="AI 호출 실패") as exc:
        GeminiRecognizer("secret-key-123", client=client, sleep=lambda s: None).recognize(
            b"img", "v1"
        )
    assert "secret-key-123" not in str(exc.value) and "***" in str(exc.value)


def test_network_error_is_wrapped_without_key():
    client = fake_client([ConnectionError("https://x?key=secret-key-123 timed out")])
    with pytest.raises(RecognitionError, match="AI 호출 실패") as exc:
        GeminiRecognizer("secret-key-123", client=client, sleep=lambda s: None).recognize(
            b"img", "v1"
        )
    assert "secret-key-123" not in str(exc.value)


def unavailable_error():
    return errors.APIError(
        503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}
    )


def test_retries_on_unavailable_then_succeeds():
    sleeps = []
    client = fake_client([unavailable_error(), ok_text(food_json)])
    r = GeminiRecognizer("k", client=client, sleep=sleeps.append).recognize(b"img", "v1")
    assert r.total_amount == 96000 and sleeps == [1]


def test_gives_up_after_unavailable_retries():
    client = fake_client([unavailable_error()] * 4)
    with pytest.raises(RecognitionError, match="응답하지 않아요"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 4


def test_server_error_500_is_not_retried():
    client = fake_client([server_error(), ok_text(food_json)])
    with pytest.raises(RecognitionError, match="AI 호출 실패"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 1


def test_default_client_has_http_timeout():
    r = GeminiRecognizer("dummy-key")
    assert r._client._api_client._http_options.timeout == HTTP_TIMEOUT_MS == 60_000


def test_missing_api_key():
    with pytest.raises(RecognitionError, match="API 키"):
        GeminiRecognizer("")


def test_unknown_prompt_version_is_recognition_error():
    client = fake_client([ok_text(food_json)])
    with pytest.raises(RecognitionError, match="v999"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v999")
