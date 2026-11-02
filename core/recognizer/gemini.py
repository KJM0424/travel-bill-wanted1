"""Gemini로 영수증 이미지를 인식한다."""

import time
from collections.abc import Callable

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from core.recognizer.base import RecognitionError, load_prompt
from core.schema import Receipt

DEFAULT_MODEL = "gemini-3.5-flash"
HTTP_TIMEOUT_MS = 60_000
# 사용자에게 보이는 안내. SDK의 영어 원문(JSON)은 보여 주지 않는다. 키가 섞여 나올 수도 있다.
MESSAGES = {
    "bad_key": "AI 키가 맞지 않거나 쓸 권한이 없어요. 앱 설정의 GEMINI_API_KEY를 확인해 주세요.",
    "daily_quota": "오늘 쓸 수 있는 AI 횟수를 다 썼어요. 내일 다시 읽을 수 있어요.",
    "rate_limit": "AI 요청이 한꺼번에 몰렸어요. 1분쯤 뒤에 다시 올려 주세요.",
    "busy": "AI 서버가 바빠서 응답하지 않아요. 잠시 뒤에 다시 올려 주세요.",
    "no_model": "쓸 수 없는 AI 모델이에요: {model}. 앱 설정의 GEMINI_MODEL을 확인해 주세요.",
    "network": "AI 서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 올려 주세요.",
    "server": "AI 서버에서 오류가 났어요(HTTP {code}). 잠시 뒤에 다시 올려 주세요.",
}
# 잠시 기다리면 풀리는 오류: 분당 한도 초과(429), 서버 과부하(503). 하루 한도는 기다려도 안 풀린다.
RETRY_KINDS = {429: "rate_limit", 503: "busy"}
FORMAT_RETRIES = 1


class GeminiRecognizer:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        client=None,
        sleep: Callable[[float], None] = time.sleep,
        max_rate_retries: int = 3,
    ):
        if not api_key:
            raise RecognitionError("Gemini API 키가 설정되지 않았어요.")
        self._api_key = api_key
        self._model = model
        self._client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_MS)
        )
        self._sleep = sleep
        self._max_rate_retries = max_rate_retries

    def recognize(self, image: bytes, prompt_version: str) -> Receipt:
        try:
            prompt = load_prompt(prompt_version)
        except ValueError as e:
            raise RecognitionError(str(e)) from None
        contents = [types.Part.from_bytes(data=image, mime_type="image/jpeg"), prompt]
        config = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=Receipt, temperature=0
        )
        for attempt in range(FORMAT_RETRIES + 1):
            text = self._generate(contents, config)
            try:
                return Receipt.model_validate_json(text or "")
            except ValidationError:
                if attempt == FORMAT_RETRIES:
                    raise RecognitionError("AI 응답 형식이 올바르지 않아요.") from None
        raise AssertionError("unreachable")

    def _generate(self, contents: list, config: types.GenerateContentConfig) -> str | None:
        """429·503은 1, 2, 4초… 간격으로 재시도한다. 그 밖의 오류는 RecognitionError로 바꾼다."""
        for attempt in range(self._max_rate_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
                return response.text
            except errors.APIError as e:
                kind = _kind(e)
                if kind not in RETRY_KINDS.values() or attempt == self._max_rate_retries:
                    raise RecognitionError(self._message(kind, e.code)) from None
                self._sleep(2**attempt)
            except Exception:  # noqa: BLE001
                # 네트워크·타임아웃 등 SDK 밖의 오류도 사용자 메시지로 바꾼다.
                raise RecognitionError(MESSAGES["network"]) from None
        raise AssertionError("unreachable")

    def _message(self, kind: str, code: int) -> str:
        return MESSAGES[kind].format(model=self._model, code=code)


def _kind(error: errors.APIError) -> str:
    """API 오류를 안내 종류로 나눈다. 키 오류는 400 INVALID_ARGUMENT로도 온다."""
    details = str(error.details)
    if error.code in (401, 403) or "API_KEY_INVALID" in details:
        return "bad_key"
    if error.code == 429:
        # 하루 한도의 quotaId는 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' 꼴이다.
        return "daily_quota" if "PerDay" in details else "rate_limit"
    if error.code == 404:
        return "no_model"
    return RETRY_KINDS.get(error.code, "server")
