"""인식기 공통 계약: 프로토콜, 오류, 프롬프트 로딩."""

import re
from pathlib import Path
from typing import Protocol

from core.schema import Receipt

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class RecognitionError(Exception):
    """인식 실패. 메시지는 사용자에게 그대로 보여 줄 수 있는 한국어 문장이다."""


class Recognizer(Protocol):
    def recognize(self, image: bytes, prompt_version: str) -> Receipt: ...


def load_prompt(version: str) -> str:
    """prompts/{version}.md를 읽는다. version은 v1, v2 같은 형식만 받는다."""
    path = PROMPTS_DIR / f"{version}.md"
    if not re.fullmatch(r"v\d+", version) or not path.exists():
        raise ValueError(f"프롬프트 버전 '{version}'을 찾을 수 없습니다.")
    return path.read_text(encoding="utf-8")
