"""API 호출 없이 fixture JSON을 돌려주는 인식기. UI 개발과 테스트에 쓴다."""

from pathlib import Path

from core.image_utils import image_hash
from core.schema import Receipt

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "receipts"


class MockRecognizer:
    def __init__(self, fixtures_dir: Path = DEFAULT_FIXTURES_DIR):
        paths = sorted(Path(fixtures_dir).glob("*.json"))
        if not paths:
            raise ValueError(f"미리 저장한 인식 결과가 없어요: {fixtures_dir}")
        self._fixtures = [Receipt.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]

    def recognize(self, image: bytes, prompt_version: str) -> Receipt:
        """같은 이미지에는 항상 같은 fixture를 고른다."""
        index = int(image_hash(image), 16) % len(self._fixtures)
        return self._fixtures[index].model_copy(deep=True)
