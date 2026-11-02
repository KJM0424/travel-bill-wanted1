import pytest

from core.recognizer import MockRecognizer, load_prompt


def test_load_prompt_v1_mentions_actual_paid_amount():
    assert "실제 결제" in load_prompt("v1")


def test_load_prompt_unknown_version():
    with pytest.raises(ValueError):
        load_prompt("v999")


def test_load_prompt_rejects_path_traversal():
    with pytest.raises(ValueError):
        load_prompt("../CLAUDE")


def test_mock_is_deterministic_per_image():
    m = MockRecognizer()
    assert m.recognize(b"img-1", "v1") == m.recognize(b"img-1", "v1")


def test_mock_returns_valid_receipts_for_all_fixtures():
    m = MockRecognizer()
    kinds = {m.recognize(bytes([i]), "v1").doc_type for i in range(40)}
    assert {"receipt", "not_receipt"} <= kinds


def test_prompt_v2_fixes_v1_failures():
    # v1 실패: 예약 캡처의 체크인·대여 시각을 결제 시각으로, 회전 영수증의 과세물품가액을 결제 금액으로 읽었다.
    from core.recognizer.base import load_prompt

    v2 = load_prompt("v2")
    assert load_prompt("v1") in v2
    for word in ("체크인", "대여", "결제일", "과세물품가액", "부가세", "결제금액"):
        assert word in v2, word


def test_app_uses_prompt_v2():
    # v2가 로컬 모델 기준 핵심 3필드 76.9% → 92.3%로 나아져 앱 기본값으로 쓴다(docs/ai-log.md 3장).
    from ui.upload_step import PROMPT_VERSION

    assert PROMPT_VERSION == "v2"
