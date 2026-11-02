"""이 컴퓨터에서 도는 Ollama 비전 모델로 영수증 이미지를 인식한다. 배포 환경에서는 쓰지 않는다."""

import base64

import requests
from pydantic import ValidationError

from core.recognizer.base import RecognitionError, load_prompt
from core.schema import Receipt

# thinking 버전(qwen3-vl:8b)은 생각 단계 때문에 같은 영수증에 3배 오래 걸렸다.
DEFAULT_MODEL = "qwen3-vl:8b-instruct"
DEFAULT_HOST = "http://localhost:11434"
# 업로드는 3장씩 동시에 보내고 Ollama는 차례로 처리하므로, 앞 요청을 기다리는 시간까지 넉넉히 준다.
HTTP_TIMEOUT_S = 300
FORMAT_RETRIES = 1


class OllamaRecognizer:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        session: requests.Session | None = None,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self._session = session or requests.Session()

    def recognize(self, image: bytes, prompt_version: str) -> Receipt:
        try:
            prompt = load_prompt(prompt_version)
        except ValueError as e:
            raise RecognitionError(str(e)) from None
        body = {
            "model": self.model,
            "stream": False,
            "format": Receipt.model_json_schema(),
            "options": {"temperature": 0},
            "messages": [
                {"role": "user", "content": prompt, "images": [base64.b64encode(image).decode()]}
            ],
        }
        for attempt in range(FORMAT_RETRIES + 1):
            text = self._chat(body)
            try:
                return Receipt.model_validate_json(text)
            except ValidationError:
                if attempt == FORMAT_RETRIES:
                    raise RecognitionError("AI 응답 형식이 올바르지 않아요.") from None
        raise AssertionError("unreachable")

    def _chat(self, body: dict) -> str:
        try:
            response = self._session.post(
                f"{self.host}/api/chat", json=body, timeout=HTTP_TIMEOUT_S
            )
        except requests.ConnectionError:
            raise RecognitionError(
                "로컬 AI(Ollama)에 연결할 수 없어요. Ollama 앱이 켜져 있는지 확인해 주세요."
            ) from None
        except requests.Timeout:
            raise RecognitionError("로컬 AI가 시간 안에 응답하지 않았어요.") from None
        if response.status_code == 404:
            raise RecognitionError(
                f"로컬 AI 모델이 없어요: {self.model}. 터미널에서 "
                f"'ollama pull {self.model}'로 받아 주세요."
            )
        if response.status_code != 200:
            raise RecognitionError(
                f"로컬 AI에서 오류가 났어요(HTTP {response.status_code}). 잠시 뒤에 다시 올려 주세요."
            )
        return response.json().get("message", {}).get("content") or ""
