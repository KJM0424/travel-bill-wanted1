"""core/가 사용자에게 보여 주는 문장은 화면과 같은 '~해요' 말투를 쓴다."""

from datetime import date

import pytest
from pydantic import ValidationError

from core.expense_builder import build_expenses
from core.image_utils import UnsupportedImageError, normalize_image
from core.payment_message import NO_PAYOUT_NOTICE
from core.recognize_service import MAX_FILES, RecognitionOutcome, recognize_batch
from core.recognizer import RecognitionError
from core.recognizer.base import load_prompt
from core.recognizer.gemini import RETRY_MESSAGES, GeminiRecognizer
from core.schema import Expense, Receipt, Trip
from core.settlement import readiness_errors

TRIP = {
    "name": "제주",
    "members": ["A", "B"],
    "leader": "A",
    "mode": "prepaid",
    "start_date": date(2026, 10, 10),
    "end_date": date(2026, 10, 12),
}


def trip_error(**overrides) -> str:
    with pytest.raises(ValidationError) as info:
        Trip(**(TRIP | overrides))
    return info.value.errors()[0]["msg"].removeprefix("Value error, ")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"members": []}, "참석자를 1명 이상 입력해 주세요."),
        ({"members": ["A", " "]}, "빈 참석자 이름이 있어요."),
        ({"members": ["A", "회비 지갑"]}, "'회비 지갑'은 참석자 이름으로 쓸 수 없어요."),
        ({"members": ["A", "A"]}, "참석자 이름이 중복돼요: A"),
        ({"leader": "Z"}, "대표 'Z'가 참석자 목록에 없어요."),
        ({"end_date": date(2026, 10, 9)}, "여행 종료일이 시작일보다 빨라요."),
        ({"mode": "fund", "fund_per_person": 0}, "회비형은 1인 회비를 0원보다 크게 입력해 주세요."),
    ],
)
def test_trip_validation_messages(overrides, message):
    assert trip_error(**overrides) == message


def expense(amount, payer, participants) -> Expense:
    return Expense(
        expense_id=f"e{amount}",
        source="manual",
        merchant_name="가게",
        amount=amount,
        payer=payer,
        participants=participants,
    )


def test_readiness_messages():
    assert readiness_errors(Trip(**TRIP)) == ["결제 건이 없어요."]
    errs = readiness_errors(
        Trip(
            **TRIP,
            expenses=[expense(0, "A", ["A"]), expense(1, "A", []), expense(2, "Z", ["A", "Q"])],
        )
    )
    assert errs == [
        "'가게' 금액이 0원이에요.",
        "'가게' 참석자가 없어요.",
        "'가게' 참석자 중 여행 참석자가 아닌 사람이 있어요: Q",
        "'가게' 결제자가 여행 참석자가 아니에요.",
    ]


def receipt(**overrides) -> Receipt:
    base = {
        "doc_type": "receipt",
        "merchant_name": "카페",
        "merchant_address": None,
        "paid_at": "2026-10-11T15:02",
        "total_amount": 18000,
        "currency": "KRW",
        "category": "cafe",
        "items": [],
        "warnings": [],
    }
    return Receipt(**(base | overrides))


def outcome(r: Receipt | None, error: str | None = None) -> RecognitionOutcome:
    return RecognitionOutcome(
        filename="a.jpg", image_hash="a" * 64, receipt=r, error=error, elapsed_s=0.1
    )


def test_build_notices():
    _, notes = build_expenses(
        [
            outcome(None, "AI 호출 실패"),
            outcome(receipt(doc_type="not_receipt")),
            outcome(receipt(currency="JPY")),
        ],
        Trip(**TRIP),
    )
    assert notes == [
        "a.jpg: 읽지 못했어요. AI 호출 실패. 직접 추가해 주세요.",
        "a.jpg: 영수증이 아니어서 제외했어요.",
        "a.jpg: 원화(KRW)가 아닌 결제(JPY)라서 제외했어요.",
    ]


@pytest.mark.parametrize(
    ("overrides", "warning"),
    [
        ({"total_amount": None}, "금액을 인식하지 못했어요. 직접 입력해 주세요."),
        ({"merchant_name": None}, "상호를 인식하지 못했어요."),
        ({"paid_at": "어제"}, "결제 일시를 해석하지 못했어요: 어제"),
        ({"paid_at": "2025-10-11T12:00"}, "연도를 2025년에서 2026년으로 고쳤어요."),
        ({"paid_at": "2026-09-01"}, "결제 날짜가 여행 기간 밖이에요."),
    ],
)
def test_build_warnings(overrides, warning):
    exps, _ = build_expenses([outcome(receipt(**overrides))], Trip(**TRIP))
    assert warning in exps[0].warnings


def test_payment_message_notice():
    assert NO_PAYOUT_NOTICE == "받는 분께 계좌를 확인해 주세요."


def test_recognizer_messages():
    assert RETRY_MESSAGES == {
        429: "AI 호출 한도를 넘었어요. 잠시 후 다시 시도해 주세요.",
        503: "AI 서버가 응답하지 않아요. 잠시 후 다시 시도해 주세요.",
    }
    with pytest.raises(RecognitionError) as info:
        GeminiRecognizer("")
    assert str(info.value) == "Gemini API 키가 설정되지 않았어요."
    with pytest.raises(ValueError) as info:
        load_prompt("v999")
    assert str(info.value) == "프롬프트 버전 'v999'을 찾을 수 없어요."


def test_not_image_message():
    # 괄호 안에 끼워 쓰는 문장이라 마침표를 붙이지 않는다.
    with pytest.raises(UnsupportedImageError) as info:
        normalize_image(b"%PDF-1.4")
    assert str(info.value) == "이미지 파일이 아니에요"


def test_too_many_files_message():
    with pytest.raises(ValueError) as info:
        recognize_batch([("a.png", b"")] * (MAX_FILES + 1), None, "v1", {})
    assert str(info.value) == f"한 번에 최대 {MAX_FILES}장까지 올릴 수 있어요."
