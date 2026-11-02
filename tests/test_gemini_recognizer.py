from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

from core.recognizer import RecognitionError
from core.recognizer.gemini import HTTP_TIMEOUT_MS, MESSAGES, GeminiRecognizer

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
    with pytest.raises(RecognitionError, match=MESSAGES["rate_limit"]):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 4


def test_retries_once_on_invalid_json_then_fails():
    client = fake_client([ok_text("{not json"), ok_text('{"doc_type": "?"}')])
    with pytest.raises(RecognitionError, match="형식"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 2


def recognize_error(error: Exception, key: str = "k", model: str = "gemini-3.5-flash") -> str:
    """오류 하나를 낸 뒤 사용자에게 보일 메시지를 돌려준다."""
    client = fake_client([error] * 5)
    recognizer = GeminiRecognizer(key, model=model, client=client, sleep=lambda s: None)
    with pytest.raises(RecognitionError) as exc:
        recognizer.recognize(b"img", "v1")
    return str(exc.value)


def invalid_key_error(key: str = "k"):
    # 실제 Gemini 응답 모양: 400 INVALID_ARGUMENT, details에 reason API_KEY_INVALID
    return errors.APIError(
        400,
        {
            "error": {
                "code": 400,
                "message": f"API key not valid. Please pass a valid API key. {key}",
                "status": "INVALID_ARGUMENT",
                "details": [{"reason": "API_KEY_INVALID", "domain": "googleapis.com"}],
            }
        },
    )


def daily_quota_error():
    return errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "violations": [
                            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                        ]
                    }
                ],
            }
        },
    )


def test_invalid_key_is_korean_without_raw_response():
    message = recognize_error(invalid_key_error("secret-key-123"), key="secret-key-123")
    assert message == MESSAGES["bad_key"]
    assert "secret-key-123" not in message and "INVALID_ARGUMENT" not in message


@pytest.mark.parametrize("code", [401, 403])
def test_permission_errors_point_to_key(code):
    error = errors.APIError(code, {"error": {"code": code, "message": "denied", "status": "X"}})
    assert recognize_error(error) == MESSAGES["bad_key"]


def test_daily_quota_says_tomorrow_and_does_not_retry():
    client = fake_client([daily_quota_error(), ok_text(food_json)])
    sleeps: list = []
    with pytest.raises(RecognitionError) as exc:
        GeminiRecognizer("k", client=client, sleep=sleeps.append).recognize(b"img", "v1")
    assert str(exc.value) == MESSAGES["daily_quota"] and "내일" in str(exc.value)
    assert len(client.calls) == 1 and sleeps == []


def test_per_minute_rate_limit_message_after_retries():
    assert recognize_error(rate_limit_error()) == MESSAGES["rate_limit"]


def test_missing_model_names_the_model_setting():
    error = errors.APIError(404, {"error": {"code": 404, "message": "gone", "status": "NOT_FOUND"}})
    message = recognize_error(error, model="gemini-old")
    assert "gemini-old" in message and "GEMINI_MODEL" in message


def test_other_server_error_shows_code_only():
    message = recognize_error(server_error())
    assert message == MESSAGES["server"].format(code=500)
    assert "internal" not in message and "INTERNAL" not in message


def test_network_error_is_korean_without_key():
    message = recognize_error(ConnectionError("https://x?key=secret-key-123 timed out"))
    assert message == MESSAGES["network"] and "secret-key-123" not in message


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
    with pytest.raises(RecognitionError, match=MESSAGES["busy"]):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 4


def test_server_error_500_is_not_retried():
    client = fake_client([server_error(), ok_text(food_json)])
    with pytest.raises(RecognitionError):
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


def test_default_model_is_available_to_new_keys():
    # 2026-11-02 확인: gemini-2.5-flash는 새 키에서 404(no longer available to new users)가 난다.
    from core.recognizer.gemini import DEFAULT_MODEL

    assert DEFAULT_MODEL == "gemini-3.5-flash"
