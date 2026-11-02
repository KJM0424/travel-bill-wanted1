"""core/가 사용자에게 보여 주는 문장은 화면과 같은 '~해요' 말투를 쓴다."""

import io
from datetime import date

import pytest
from PIL import Image
from pydantic import ValidationError

from core.expense_builder import build_expenses
from core.image_utils import UnsupportedImageError, normalize_image
from core.payment_message import NO_PAYOUT_NOTICE, build_message
from core.recognize_service import MAX_FILES, RecognitionOutcome, recognize_batch
from core.recognizer import RecognitionError
from core.recognizer.base import load_prompt
from core.recognizer.gemini import MESSAGES, GeminiRecognizer
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
        ({"members": []}, "함께한 사람을 1명 이상 적어 주세요."),
        ({"members": ["A", " "]}, "이름이 비어 있는 사람이 있어요."),
        ({"members": ["A", "회비 지갑"]}, "'회비 지갑'은 이름으로 쓸 수 없어요."),
        ({"members": ["A", "A"]}, "같은 이름이 두 번 있어요: A"),
        ({"leader": "Z"}, "총무 'Z'가 함께한 사람에 없어요."),
        ({"end_date": date(2026, 10, 9)}, "오는 날이 가는 날보다 빨라요."),
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
        "'가게' 함께한 사람이 없어요.",
        "'가게' 함께한 사람 중 이 여행에 없는 사람이 있어요: Q",
        "'가게' 결제한 사람이 이 여행에 없어요.",
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
            outcome(None, "AI 서버에 연결하지 못했어요"),
            outcome(receipt(doc_type="not_receipt")),
            outcome(receipt(currency="JPY")),
        ],
        Trip(**TRIP),
    )
    assert notes == [
        "a.jpg: 읽지 못했어요. AI 서버에 연결하지 못했어요. 직접 추가할 수도 있어요.",
        "a.jpg: 영수증이 아니어서 제외했어요.",
        "a.jpg: 원화(KRW)가 아닌 결제(JPY)라서 제외했어요.",
    ]


@pytest.mark.parametrize(
    ("overrides", "warning"),
    [
        ({"total_amount": None}, "금액을 읽지 못했어요. 직접 적어 주세요."),
        ({"merchant_name": None}, "가게 이름을 읽지 못했어요."),
        ({"paid_at": "어제"}, "결제 날짜를 읽지 못했어요(어제). 직접 고쳐 주세요."),
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
    assert MESSAGES == {
        "bad_key": "AI 키가 맞지 않거나 쓸 권한이 없어요. 앱 설정의 GEMINI_API_KEY를 확인해 주세요.",
        "daily_quota": "오늘 쓸 수 있는 AI 횟수를 다 썼어요. 내일 다시 읽을 수 있어요.",
        "rate_limit": "AI 요청이 한꺼번에 몰렸어요. 1분쯤 뒤에 다시 올려 주세요.",
        "busy": "AI 서버가 바빠서 응답하지 않아요. 잠시 뒤에 다시 올려 주세요.",
        "no_model": "쓸 수 없는 AI 모델이에요: {model}. 앱 설정의 GEMINI_MODEL을 확인해 주세요.",
        "network": "AI 서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 올려 주세요.",
        "server": "AI 서버에서 오류가 났어요(HTTP {code}). 잠시 뒤에 다시 올려 주세요.",
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


# --- 문구 검토(2026-11-02)에서 고친 것 ---


def test_data_notice_says_the_app_does_not_store_photos():
    from ui.upload_step import DATA_NOTICE

    assert DATA_NOTICE == (
        "사진은 Google Gemini로 보내 읽어요. 이 앱은 사진을 저장하지 않아요. "
        "카드번호와 이름은 가리고 올려 주세요."
    )


def test_unexpected_error_hides_raw_exception():
    from core.recognize_service import recognize_batch

    class Broken:
        def recognize(self, image, prompt_version):
            raise TypeError("NoneType has no attribute x")

    png = io.BytesIO()
    Image.new("RGB", (10, 10)).save(png, format="PNG")
    [outcome] = recognize_batch([("a.png", png.getvalue())], Broken(), "v1", {})
    assert outcome.error == "이 사진을 처리하다 문제가 생겼어요."


def test_no_kakao_key_notice_has_no_setting_name():
    from ui.map_view import NO_KEY_INFO

    assert "KAKAO_REST_API_KEY" not in NO_KEY_INFO and "카카오" in NO_KEY_INFO


def test_fund_mode_messages_call_the_leader_chongmu():
    from core.schema import FUND_WALLET
    from core.settlement import Transfer

    trip = Trip(**{**TRIP, "mode": "fund", "fund_per_person": 10000})
    for transfer in (Transfer("B", FUND_WALLET, 1000), Transfer(FUND_WALLET, "B", 1000)):
        message = build_message(transfer, trip)
        assert "총무" in message and "대표" not in message
