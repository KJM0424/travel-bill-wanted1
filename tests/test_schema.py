from datetime import date, datetime

import pytest
from pydantic import ValidationError

from core.schema import Expense, Receipt, Trip, parse_paid_at


def make_trip(**overrides):
    base = {
        "name": "제주",
        "members": ["민수", "지영", "철수"],
        "leader": "민수",
        "mode": "prepaid",
        "start_date": date(2026, 10, 10),
        "end_date": date(2026, 10, 12),
    }
    return Trip(**(base | overrides))


def test_trip_strips_member_names():
    assert make_trip(members=[" 민수 ", "지영"]).members == ["민수", "지영"]


@pytest.mark.parametrize("members", [["민수", "민수"], ["민수", "  "], ["민수", "회비 지갑"], []])
def test_trip_rejects_bad_members(members):
    with pytest.raises(ValidationError):
        make_trip(members=members)


def test_trip_duplicate_member_message_is_korean():
    with pytest.raises(ValidationError, match="같은 이름이 두 번 있어요: 민수"):
        make_trip(members=["민수", "민수"])


def test_trip_rejects_leader_not_in_members():
    with pytest.raises(ValidationError):
        make_trip(leader="영희")


def test_trip_rejects_end_before_start():
    with pytest.raises(ValidationError):
        make_trip(end_date=date(2026, 10, 9))


def test_fund_mode_requires_positive_fee():
    with pytest.raises(ValidationError):
        make_trip(mode="fund", fund_per_person=0)


def test_expense_rejects_negative_amount():
    with pytest.raises(ValidationError):
        Expense(
            expense_id="e1",
            source="manual",
            merchant_name="x",
            amount=-1,
            payer="민수",
            participants=[],
        )


def test_parse_paid_at_with_time():
    assert parse_paid_at("2026-10-12T19:42") == (datetime(2026, 10, 12, 19, 42), True)


def test_parse_paid_at_date_only():
    assert parse_paid_at("2026-10-12") == (datetime(2026, 10, 12), False)


@pytest.mark.parametrize("value", [None, "", "어제 저녁", "2026-13-01"])
def test_parse_paid_at_invalid_returns_none(value):
    assert parse_paid_at(value) == (None, False)


def test_receipt_schema_has_no_card_number_field():
    props = Receipt.model_json_schema()["properties"]
    assert not any(k in props for k in ["card_number", "approval_number", "phone"])


def test_receipt_schema_has_no_defaults_for_gemini():
    # 기본값이 없어야 Gemini가 모든 필드를 빠짐없이 채워서 응답한다.
    props = Receipt.model_json_schema()["properties"]
    assert not any("default" in p for p in props.values())
