import pytest

from core.schema import Receipt
from eval.metrics import normalize_merchant, score_case, summarize


def receipt(doc_type="receipt", merchant="스타벅스", paid_at="2026-10-11T15:02", total=18000):
    return Receipt(
        doc_type=doc_type,
        merchant_name=merchant,
        merchant_address=None,
        paid_at=paid_at,
        total_amount=total,
        currency="KRW",
        category="cafe",
        items=[],
        warnings=[],
    )


def row(source, core3, t, error=None):
    fields = {k: core3 for k in ("doc_type", "merchant_name", "paid_at", "total_amount")}
    return {"source": source, **fields, "core3": core3, "seconds": t, "error": error}


@pytest.mark.parametrize(
    "a,b",
    [("스타벅스 애월점", "스타벅스"), ("흑돼지 명가", "흑돼지명가"), ("(주)이마트24 제주점", "이마트24")],
)
def test_normalize_merchant_equivalents(a, b):
    assert normalize_merchant(a) == normalize_merchant(b)


def test_normalize_merchant_keeps_single_token_ending_in_jeom():
    assert normalize_merchant("편의점") == "편의점"


def test_core3_requires_all_three():
    exp = {
        "doc_type": "receipt",
        "merchant_name": "스타벅스",
        "paid_at": "2026-10-11T15:02",
        "total_amount": 18000,
    }
    s = score_case(exp, receipt(merchant="스타벅스 애월점", paid_at="2026-10-11T15:02", total=18000))
    assert s["core3"] is True
    assert (
        score_case(exp, receipt(merchant="스타벅스", paid_at="2026-10-11T15:03", total=18000))[
            "core3"
        ]
        is False
    )


def test_not_receipt_case_scored_on_doc_type_only():
    exp = {"doc_type": "not_receipt", "merchant_name": None, "paid_at": None, "total_amount": None}
    assert score_case(exp, receipt(doc_type="not_receipt", total=None))["core3"] is True


def test_failed_recognition_scores_false():
    exp = {"doc_type": "receipt", "merchant_name": "x", "paid_at": None, "total_amount": 1}
    assert score_case(exp, None)["core3"] is False


def test_summarize_splits_by_source():
    df = summarize(
        [
            row("real", core3=True, t=2.0),
            row("real", core3=False, t=4.0, error="x"),
            row("synthetic", core3=True, t=1.0),
        ]
    )
    real = df.loc["real"]
    assert real["core3"] == 0.5 and real["avg_seconds"] == 3.0 and real["error_rate"] == 0.5
    assert df.loc["all"]["core3"] == pytest.approx(2 / 3)
