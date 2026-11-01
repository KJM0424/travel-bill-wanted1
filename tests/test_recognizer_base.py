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
