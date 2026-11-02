import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from core.recognizer import RecognitionError
from core.recognizer.ollama import DEFAULT_HOST, DEFAULT_MODEL, OllamaRecognizer

FIXTURES = Path(__file__).parent / "fixtures" / "receipts"
food_json = (FIXTURES / "food.json").read_text(encoding="utf-8")


class FakeSession:
    """requests.Session 대신 응답(또는 예외)을 순서대로 돌려준다."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list = []

    def post(self, url, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def reply(content: str, status: int = 200):
    return SimpleNamespace(status_code=status, json=lambda: {"message": {"content": content}})


def error_reply(status: int, message: str = "error"):
    return SimpleNamespace(status_code=status, json=lambda: {"error": message})


def test_recognize_returns_receipt_and_sends_schema_and_image():
    session = FakeSession([reply(food_json)])
    receipt = OllamaRecognizer(session=session).recognize(b"img", "v1")
    assert receipt.merchant_name
    call = session.calls[0]
    assert call["url"] == f"{DEFAULT_HOST}/api/chat"
    body = call["json"]
    assert body["model"] == DEFAULT_MODEL and body["stream"] is False
    assert body["format"]["properties"]["total_amount"]
    assert body["options"]["temperature"] == 0
    assert body["messages"][0]["images"] == [base64.b64encode(b"img").decode()]


def test_default_model_is_non_thinking_variant():
    # thinking 버전(qwen3-vl:8b)은 같은 영수증에 3배 오래 걸렸다.
    assert DEFAULT_MODEL == "qwen3-vl:8b-instruct"


def test_host_trailing_slash_is_trimmed():
    session = FakeSession([reply(food_json)])
    OllamaRecognizer(host="http://pc.local:11434/", session=session).recognize(b"img", "v1")
    assert session.calls[0]["url"] == "http://pc.local:11434/api/chat"


def test_invalid_json_retries_once_then_succeeds():
    session = FakeSession([reply("not json"), reply(food_json)])
    assert OllamaRecognizer(session=session).recognize(b"img", "v1").merchant_name
    assert len(session.calls) == 2


def test_invalid_json_twice_raises_korean_error():
    session = FakeSession([reply("{}"), reply("{}")])
    with pytest.raises(RecognitionError, match="AI 응답 형식이 올바르지 않아요"):
        OllamaRecognizer(session=session).recognize(b"img", "v1")


def test_server_not_running_tells_to_open_ollama():
    session = FakeSession([requests.ConnectionError("refused")])
    with pytest.raises(RecognitionError, match="Ollama 앱이 켜져 있는지"):
        OllamaRecognizer(session=session).recognize(b"img", "v1")


def test_timeout_has_korean_message():
    session = FakeSession([requests.Timeout("slow")])
    with pytest.raises(RecognitionError, match="로컬 AI가 시간 안에 응답하지 않았어요"):
        OllamaRecognizer(session=session).recognize(b"img", "v1")


def test_missing_model_tells_how_to_pull():
    session = FakeSession([error_reply(404, "model 'x' not found")])
    with pytest.raises(RecognitionError, match="ollama pull qwen3-vl:8b-instruct"):
        OllamaRecognizer(session=session).recognize(b"img", "v1")


def test_other_http_error_is_reported():
    session = FakeSession([error_reply(500, "boom")])
    with pytest.raises(RecognitionError, match=r"로컬 AI에서 오류가 났어요\(HTTP 500\)"):
        OllamaRecognizer(session=session).recognize(b"img", "v1")


def test_unknown_prompt_version_raises_recognition_error():
    with pytest.raises(RecognitionError):
        OllamaRecognizer(session=FakeSession([])).recognize(b"img", "v999")
