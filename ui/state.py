"""세션 상태 접근, 참석자 동기화, 인식기 선택, 화면용 오류 문장."""

from collections.abc import Iterable, MutableMapping
from typing import Any

import streamlit as st
from pydantic import ValidationError

from core.config import get_setting
from core.recognizer import MockRecognizer, RecognitionError, Recognizer
from core.schema import FUND_WALLET, Trip

START_STEP = "시작"
STEPS = ["설정", "업로드", "검토", "정산"]
# 진행 표시에 쓰는 이름. 단계 값(STEPS)은 세션·테스트에서 쓰므로 그대로 둔다.
STEP_LABELS = {"설정": "설정", "업로드": "영수증", "검토": "확인", "정산": "정산"}

# 검토 화면 위젯 key의 접두어. 여행이 밖에서 바뀌면 이 위젯 값을 지워 여행 값으로 다시 채운다.
REVIEW_WIDGET_PREFIXES = ("part_", "excl_", "rv_")
SETUP_WIDGET_PREFIX = "setup_"
UPLOAD_OUTCOME_KEYS = ("upload_notices", "upload_error", "upload_added")

FIELD_LABELS = {
    "name": "여행 이름",
    "members": "참석자",
    "leader": "대표",
    "mode": "정산 방식",
    "fund_per_person": "1인 회비",
    "start_date": "시작일",
    "end_date": "종료일",
    "payout": "송금 정보",
    "expenses": "결제 건",
}


def session() -> MutableMapping[str, Any]:
    """세션 상태는 이 함수로만 접근한다. 테스트에서 dict로 바꿔 끼운다."""
    return st.session_state


def get_trip() -> Trip | None:
    return session().get("trip")


def set_trip(trip: Trip) -> None:
    session()["trip"] = trip


def go_to(step: str) -> None:
    """버튼 on_click 콜백으로 쓴다. 위젯이 그려지기 전에 불려야 단계 radio를 바꿀 수 있다."""
    session()["step"] = step


def init_widget(key: str, value: Any) -> None:
    """위젯 값이 아직 없을 때만 넣는다. 위젯에는 value 인자를 주지 않는다."""
    state = session()
    if key not in state:
        state[key] = value


def clear_widgets(prefixes: Iterable[str], keep: Iterable[str] = ()) -> None:
    state = session()
    prefixes, keep = tuple(prefixes), set(keep)
    for key in [k for k in state if str(k).startswith(prefixes) and k not in keep]:
        del state[key]


def clear_review_widgets() -> None:
    clear_widgets(REVIEW_WIDGET_PREFIXES)


def clear_upload_outcome() -> None:
    """지난 업로드의 안내·오류·추가 건수를 지운다. 다른 여행을 불러오면 맞지 않는 안내다."""
    for key in UPLOAD_OUTCOME_KEYS:
        session().pop(key, None)


def sync_members(trip: Trip, members: list[str], leader: str) -> Trip:
    """빠진 사람을 결제 건 참석자와 송금 정보에서 지운다. 결제자가 빠진 사람이면 대표로 바꾼다.

    model_copy는 검증을 건너뛰므로 model_validate로 다시 만든다.
    """
    names = [m.strip() for m in members]
    keep = set(names)
    allowed_payers = keep | ({FUND_WALLET} if trip.mode == "fund" else set())
    data = trip.model_dump()
    expenses = []
    for expense in data["expenses"]:
        expense["participants"] = [p for p in expense["participants"] if p in keep]
        if expense["payer"] not in allowed_payers:
            expense["payer"] = leader.strip()
        expenses.append(expense)
    payout = {name: info for name, info in data["payout"].items() if name in keep}
    return Trip.model_validate(
        {**data, "members": names, "leader": leader, "expenses": expenses, "payout": payout}
    )


def add_members_to_expenses(trip: Trip, names: list[str]) -> Trip:
    """새로 들어온 사람을 모든 결제 건 참석자로 체크한다(기본 전원 체크). 순서는 members 순서다."""
    new = set(names)
    data = trip.model_dump()
    for expense in data["expenses"]:
        joined = set(expense["participants"]) | new
        expense["participants"] = [m for m in trip.members if m in joined]
    return Trip.model_validate(data)


def validation_messages(error: ValidationError) -> list[str]:
    """pydantic 오류를 화면에 보여 줄 한국어 문장으로 바꾼다. 영어 원문은 보여 주지 않는다."""
    messages = []
    for item in error.errors():
        if item["type"] == "value_error" and "error" in item.get("ctx", {}):
            messages.append(str(item["ctx"]["error"]))
        elif item["msg"].startswith("Value error, "):
            messages.append(item["msg"].removeprefix("Value error, "))
        else:
            field = FIELD_LABELS.get(str(item["loc"][0]) if item["loc"] else "", "입력")
            messages.append(f"{field} 값이 올바르지 않아요.")
    return list(dict.fromkeys(messages))


def recognizer_name() -> str:
    return (get_setting("RECOGNIZER") or "gemini").strip().lower()


def get_recognizer() -> Recognizer:
    """RECOGNIZER가 mock이면 Mock, ollama면 로컬 모델, 아니면 Gemini. 키가 없으면 RecognitionError."""
    if recognizer_name() == "mock":
        return MockRecognizer()
    if recognizer_name() == "ollama":
        from core.recognizer.ollama import DEFAULT_HOST, DEFAULT_MODEL, OllamaRecognizer

        return OllamaRecognizer(
            model=get_setting("OLLAMA_MODEL") or DEFAULT_MODEL,
            host=get_setting("OLLAMA_HOST") or DEFAULT_HOST,
        )
    # google-genai import가 무거워서 Gemini를 쓸 때만 불러온다.
    from core.recognizer.gemini import DEFAULT_MODEL, GeminiRecognizer

    api_key = get_setting("GEMINI_API_KEY")
    if not api_key:
        raise RecognitionError("Gemini API 키가 설정되지 않았어요.")
    return GeminiRecognizer(api_key=api_key, model=get_setting("GEMINI_MODEL") or DEFAULT_MODEL)
