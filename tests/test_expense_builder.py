from datetime import date, datetime

from core.expense_builder import build_expenses, find_duplicates, sort_expenses
from core.recognize_service import RecognitionOutcome
from core.schema import FUND_WALLET, Expense, Receipt, Trip

TRIP_BASE = {
    "name": "제주",
    "members": ["A", "B", "C"],
    "leader": "A",
    "start_date": date(2026, 10, 10),
    "end_date": date(2026, 10, 12),
}
prepaid_trip = Trip(**TRIP_BASE, mode="prepaid")
fund_trip = Trip(**TRIP_BASE, mode="fund", fund_per_person=100000)


def receipt(
    total=18000, paid_at="2026-10-11T15:02", doc_type="receipt", currency="KRW", merchant="카페"
):
    return Receipt(
        doc_type=doc_type,
        merchant_name=merchant,
        merchant_address=None,
        paid_at=paid_at,
        total_amount=total,
        currency=currency,
        category="cafe",
        items=[],
        warnings=[],
    )


def outcome(r, name="a.jpg", hash_="a" * 64):
    return RecognitionOutcome(filename=name, image_hash=hash_, receipt=r, error=None, elapsed_s=0.1)


def failed_outcome(name, error):
    return RecognitionOutcome(
        filename=name, image_hash="f" * 64, receipt=None, error=error, elapsed_s=0.1
    )


def mk(id, amount=1000, paid_at=None, time_known=False):
    return Expense(
        expense_id=id,
        source="ai",
        merchant_name="x",
        paid_at=paid_at,
        time_known=time_known,
        amount=amount,
        payer="A",
        participants=["A"],
    )


def test_receipt_becomes_expense_with_defaults():
    exps, _notes = build_expenses(
        [outcome(receipt(total=96000, paid_at="2026-10-11T19:42"))], prepaid_trip
    )
    e = exps[0]
    assert (e.amount, e.payer, e.participants, e.time_known) == (96000, "A", ["A", "B", "C"], True)


def test_participants_are_not_shared_with_trip():
    exps, _ = build_expenses([outcome(receipt())], prepaid_trip)
    exps[0].participants.remove("B")
    assert prepaid_trip.members == ["A", "B", "C"]


def test_fund_mode_default_payer_is_wallet():
    exps, _ = build_expenses([outcome(receipt())], fund_trip)
    assert exps[0].payer == FUND_WALLET


def test_not_receipt_and_foreign_currency_are_excluded_with_notice():
    exps, notes = build_expenses(
        [
            outcome(receipt(doc_type="not_receipt"), name="cat.jpg"),
            outcome(receipt(currency="JPY"), name="tokyo.jpg"),
        ],
        prepaid_trip,
    )
    assert (
        exps == [] and any("cat.jpg" in n for n in notes) and any("tokyo.jpg" in n for n in notes)
    )


def test_failed_outcome_becomes_notice():
    _, notes = build_expenses([failed_outcome("x.jpg", "AI 호출 실패")], prepaid_trip)
    assert any("x.jpg" in n and "직접 추가" in n for n in notes)


def test_missing_amount_becomes_zero_with_warning():
    exps, _ = build_expenses([outcome(receipt(total=None))], prepaid_trip)
    assert exps[0].amount == 0 and any("금액" in w for w in exps[0].warnings)


def test_missing_merchant_gets_placeholder_name():
    exps, _ = build_expenses([outcome(receipt(merchant=None))], prepaid_trip)
    assert exps[0].merchant_name and any("상호" in w for w in exps[0].warnings)


def test_wrong_year_corrected_to_trip_year():
    exps, _ = build_expenses([outcome(receipt(paid_at="2025-10-11T12:00"))], prepaid_trip)
    assert exps[0].paid_at.year == 2026 and any("연도" in w for w in exps[0].warnings)


def test_out_of_range_date_warns_but_keeps():
    exps, _ = build_expenses([outcome(receipt(paid_at="2026-09-01"))], prepaid_trip)
    assert len(exps) == 1 and any("여행 기간" in w for w in exps[0].warnings)


def test_same_image_twice_gets_distinct_ids():
    exps, _ = build_expenses([outcome(receipt()), outcome(receipt())], prepaid_trip)
    assert [e.expense_id for e in exps] == ["a" * 12, "a" * 12 + "-2"]


def test_sort_date_only_first_in_day_and_unknown_last():
    a = mk(paid_at=datetime(2026, 10, 11, 9, 0), time_known=True, id="a")
    b = mk(paid_at=datetime(2026, 10, 11), time_known=False, id="b")
    c = mk(paid_at=None, id="c")
    d = mk(paid_at=datetime(2026, 10, 10, 20, 0), time_known=True, id="d")
    assert [e.expense_id for e in sort_expenses([a, b, c, d])] == ["d", "b", "a", "c"]


def test_find_duplicates_within_10_minutes_same_amount():
    a = mk(amount=18000, paid_at=datetime(2026, 10, 11, 15, 0), time_known=True, id="a")
    b = mk(amount=18000, paid_at=datetime(2026, 10, 11, 15, 9), time_known=True, id="b")
    c = mk(amount=18000, paid_at=datetime(2026, 10, 11, 15, 30), time_known=True, id="c")
    assert find_duplicates([a, b, c]) == [("a", "b")]


def test_find_duplicates_ignores_different_amounts_and_unknown_time():
    a = mk(amount=18000, paid_at=datetime(2026, 10, 11, 15, 0), time_known=True, id="a")
    b = mk(amount=18500, paid_at=datetime(2026, 10, 11, 15, 1), time_known=True, id="b")
    c = mk(amount=18000, paid_at=datetime(2026, 10, 11), time_known=False, id="c")
    assert find_duplicates([b, c, a]) == []


def test_existing_ids_are_not_reused_across_uploads():
    first, _ = build_expenses([outcome(receipt())], prepaid_trip)
    second, _ = build_expenses(
        [outcome(receipt()), outcome(receipt())],
        prepaid_trip,
        existing_ids=[e.expense_id for e in first],
    )
    assert [e.expense_id for e in second] == ["a" * 12 + "-2", "a" * 12 + "-3"]
