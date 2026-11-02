"""여러 이미지를 병렬로 인식한다. 한 장이 실패해도 나머지는 계속한다."""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from core.image_utils import UnsupportedImageError, image_hash, normalize_image
from core.recognizer import RecognitionError, Recognizer
from core.schema import Receipt

MAX_FILES = 30
# 예상하지 못한 오류. 영어 원문은 보여 주지 않는다.
UNEXPECTED_ERROR = "이 사진을 처리하다 문제가 생겼어요."


@dataclass
class RecognitionOutcome:
    filename: str
    image_hash: str
    receipt: Receipt | None
    error: str | None
    elapsed_s: float


def recognize_batch(
    files: list[tuple[str, bytes]],
    recognizer: Recognizer,
    prompt_version: str,
    cache: dict[str, Receipt],
    max_workers: int = 3,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[RecognitionOutcome]:
    """결과는 입력 순서대로 돌려준다. cache는 원본 이미지 해시 → 인식 결과다."""
    if len(files) > MAX_FILES:
        raise ValueError(f"한 번에 최대 {MAX_FILES}장까지 올릴 수 있어요.")
    outcomes: list[RecognitionOutcome | None] = [None] * len(files)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_recognize_one, name, raw, recognizer, prompt_version, cache): i
            for i, (name, raw) in enumerate(files)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            outcome = future.result()
            outcomes[futures[future]] = outcome
            if outcome.receipt is not None:
                cache[outcome.image_hash] = outcome.receipt
            if on_progress:
                on_progress(done, len(files))
    return outcomes


def _recognize_one(
    filename: str,
    raw: bytes,
    recognizer: Recognizer,
    prompt_version: str,
    cache: dict[str, Receipt],
) -> RecognitionOutcome:
    started = time.perf_counter()
    digest = image_hash(raw)
    receipt, error = None, None
    try:
        image = normalize_image(raw)
        cached = cache.get(digest)
        if cached is not None:
            receipt = cached.model_copy(deep=True)
        else:
            receipt = recognizer.recognize(image, prompt_version)
    except (UnsupportedImageError, RecognitionError) as e:
        error = str(e)
    except Exception:  # noqa: BLE001
        # 예상하지 못한 오류도 이 파일만 실패로 처리하고 나머지는 계속한다.
        error = UNEXPECTED_ERROR
    return RecognitionOutcome(filename, digest, receipt, error, time.perf_counter() - started)
