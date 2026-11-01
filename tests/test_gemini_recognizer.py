from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

from core.recognizer import RecognitionError
from core.recognizer.gemini import GeminiRecognizer

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
    client = fake_client([server_error()])
    with pytest.raises(RecognitionError, match="AI 호출 실패") as exc:
        GeminiRecognizer("secret-key-123", client=client, sleep=lambda s: None).recognize(
            b"img", "v1"
        )
    assert "secret-key-123" not in str(exc.value)


def test_missing_api_key():
    with pytest.raises(RecognitionError, match="API 키"):
        GeminiRecognizer("")


def test_unknown_prompt_version_is_recognition_error():
    client = fake_client([ok_text(food_json)])
    with pytest.raises(RecognitionError, match="v999"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v999")
