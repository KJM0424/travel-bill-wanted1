import io

import pytest
from PIL import Image

from core.recognize_service import recognize_batch
from core.recognizer import MockRecognizer, RecognitionError


def png(color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), color).save(buf, format="PNG")
    return buf.getvalue()


class CountingRecognizer:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def recognize(self, image, prompt_version):
        self.calls += 1
        return self.inner.recognize(image, prompt_version)


class AlwaysFails:
    def __init__(self, message):
        self.message = message

    def recognize(self, image, prompt_version):
        raise RecognitionError(self.message)


def test_rejects_more_than_30_files():
    with pytest.raises(ValueError, match="30"):
        recognize_batch([("a.jpg", png())] * 31, MockRecognizer(), "v1", {})


def test_one_failure_does_not_stop_others():
    files = [("ok.png", png()), ("bad.pdf", b"%PDF"), ("ok2.png", png(color="red"))]
    out = recognize_batch(files, MockRecognizer(), "v1", {})
    assert [o.error is None for o in out] == [True, False, True]
    assert "이미지 파일이 아니에요" in out[1].error


def test_keeps_input_order():
    files = [(f"{i}.png", png(color=(i, 0, 0))) for i in range(6)]
    out = recognize_batch(files, MockRecognizer(), "v1", {})
    assert [o.filename for o in out] == [f for f, _ in files]


def test_cache_avoids_second_call():
    counting = CountingRecognizer(MockRecognizer())
    cache = {}
    recognize_batch([("a.png", png())], counting, "v1", cache)
    recognize_batch([("a.png", png())], counting, "v1", cache)
    assert counting.calls == 1


def test_recognition_error_becomes_outcome_error():
    out = recognize_batch([("a.png", png())], AlwaysFails("AI 호출 실패: 시간 초과"), "v1", {})
    assert out[0].receipt is None and "시간 초과" in out[0].error


def test_progress_callback_reaches_total():
    seen = []
    recognize_batch(
        [("a.png", png()), ("b.png", png(color="blue"))],
        MockRecognizer(),
        "v1",
        {},
        on_progress=lambda d, t: seen.append((d, t)),
    )
    assert seen[-1] == (2, 2)


class FailsOnRed:
    """빨간 이미지에서만 예상하지 못한 예외를 던진다."""

    def recognize(self, image, prompt_version):
        r, g, _ = Image.open(io.BytesIO(image)).getpixel((0, 0))
        if r > 200 and g < 50:
            raise RuntimeError("boom")
        return MockRecognizer().recognize(image, prompt_version)


def test_unexpected_error_in_one_file_does_not_stop_others():
    files = [("ok.png", png()), ("red.png", png(color="red"))]
    out = recognize_batch(files, FailsOnRed(), "v1", {})
    assert out[0].receipt is not None
    assert out[1].receipt is None and "boom" in out[1].error
