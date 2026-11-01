"""Gemini로 영수증 이미지를 인식한다."""

import time
from collections.abc import Callable

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from core.recognizer.base import RecognitionError, load_prompt
from core.schema import Receipt

DEFAULT_MODEL = "gemini-2.5-flash"
RATE_LIMIT_CODE = 429
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
            raise RecognitionError("Gemini API 키가 설정되지 않았습니다.")
        self._api_key = api_key
        self._model = model
        self._client = client or genai.Client(api_key=api_key)
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
                    raise RecognitionError("AI 응답 형식이 올바르지 않습니다.") from None
        raise AssertionError("unreachable")

    def _generate(self, contents: list, config: types.GenerateContentConfig) -> str | None:
        """429는 1, 2, 4초… 간격으로 재시도한다. 그 밖의 오류는 RecognitionError로 바꾼다."""
        for attempt in range(self._max_rate_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
                return response.text
            except errors.APIError as e:
                if e.code != RATE_LIMIT_CODE:
                    raise RecognitionError(self._failure_message(e)) from None
                if attempt == self._max_rate_retries:
                    raise RecognitionError(
                        "AI 호출 한도를 넘었습니다. 잠시 후 다시 시도하세요."
                    ) from None
                self._sleep(2**attempt)
            except Exception as e:  # noqa: BLE001
                # 네트워크·타임아웃 등 SDK 밖의 오류도 사용자 메시지로 바꾼다.
                raise RecognitionError(self._failure_message(e)) from None
        raise AssertionError("unreachable")

    def _failure_message(self, error: Exception) -> str:
        detail = str(error).replace(self._api_key, "***")
        return f"AI 호출 실패: {type(error).__name__}: {detail}"
