"""1단계: 여행 설정 (참석자, 대표, 정산 방식, 송금 정보)."""

from datetime import date

import streamlit as st
from pydantic import ValidationError

from core.schema import Trip
from ui.state import (
    SETUP_WIDGET_PREFIX,
    clear_review_widgets,
    get_trip,
    go_to,
    init_widget,
    session,
    set_trip,
    sync_members,
    validation_messages,
)

MODE_LABELS = {"prepaid": "선결제형", "fund": "회비형"}
MODE_BY_LABEL = {label: mode for mode, label in MODE_LABELS.items()}
PAYOUT_FIELDS = [
    ("bank_account", "계좌 (은행 계좌번호 예금주)"),
    ("toss_link", "토스 송금 링크"),
    ("kakaopay_link", "카카오페이 송금 링크"),
]


def parse_members(text: str) -> list[str]:
    """쉼표로 구분한 이름. 빈 칸은 그대로 두어 검증에서 막는다."""
    if not text.strip():
        return []
    return [name.strip() for name in text.split(",")]


def render_setup() -> None:
    st.header("1. 여행 설정")
    trip = get_trip()
    _init_from_trip(trip)

    st.text_input("여행 이름", key="setup_name", placeholder="제주 2박 3일")
    start_col, end_col = st.columns(2)
    start_col.date_input("시작일", key="setup_start")
    end_col.date_input("종료일", key="setup_end")
    st.text_input("참석자 (쉼표로 구분)", key="setup_members", placeholder="민수, 지영, 철수")

    names = list(dict.fromkeys(n for n in parse_members(session()["setup_members"]) if n))
    if session().get("setup_leader") not in names:
        session().pop("setup_leader", None)
    st.selectbox("대표 (총무)", names, key="setup_leader", placeholder="참석자를 먼저 입력하세요")

    st.radio("정산 방식", list(MODE_BY_LABEL), key="setup_mode", horizontal=True)
    if session()["setup_mode"] == MODE_LABELS["fund"]:
        st.number_input("1인 회비 (원)", min_value=0, step=10000, key="setup_fee")

    with st.expander("송금 정보 (돈을 받을 수 있는 사람만 입력)"):
        for name in names:
            st.markdown(f"**{name}**")
            for field, label in PAYOUT_FIELDS:
                key = _payout_key(name, field)
                init_widget(key, "")
                st.text_input(label, key=key)

    if st.button("저장", key="setup_save", type="primary"):
        _save(trip, names)


def _init_from_trip(trip: Trip | None) -> None:
    if trip is None:
        init_widget("setup_name", "")
        init_widget("setup_start", date.today())
        init_widget("setup_end", date.today())
        init_widget("setup_members", "")
        init_widget("setup_mode", MODE_LABELS["prepaid"])
        init_widget("setup_fee", 0)
        return
    init_widget("setup_name", trip.name)
    init_widget("setup_start", trip.start_date)
    init_widget("setup_end", trip.end_date)
    init_widget("setup_members", ", ".join(trip.members))
    init_widget("setup_leader", trip.leader)
    init_widget("setup_mode", MODE_LABELS[trip.mode])
    init_widget("setup_fee", trip.fund_per_person)
    for name, info in trip.payout.items():
        for field, _ in PAYOUT_FIELDS:
            init_widget(_payout_key(name, field), getattr(info, field) or "")


def _payout_key(name: str, field: str) -> str:
    return f"{SETUP_WIDGET_PREFIX}pay_{name}_{field}"


def _collect_payout(names: list[str]) -> dict[str, dict[str, str | None]]:
    payout = {}
    for name in names:
        info = {
            f: (session().get(_payout_key(name, f)) or "").strip() or None for f, _ in PAYOUT_FIELDS
        }
        if any(info.values()):
            payout[name] = info
    return payout


def _save(previous: Trip | None, names: list[str]) -> None:
    state = session()
    mode = MODE_BY_LABEL[state["setup_mode"]]
    data = {
        "name": state["setup_name"].strip() or "여행",
        "members": parse_members(state["setup_members"]),
        "leader": state.get("setup_leader") or "",
        "mode": mode,
        "fund_per_person": int(state.get("setup_fee") or 0) if mode == "fund" else 0,
        "start_date": state["setup_start"],
        "end_date": state["setup_end"],
        "payout": _collect_payout(names),
        "expenses": [e.model_dump() for e in previous.expenses] if previous else [],
    }
    try:
        trip = Trip.model_validate(data)
        # 사람이나 방식이 바뀌었으면 기존 결제 건의 참석자·결제자를 맞춘다.
        trip = sync_members(trip, trip.members, trip.leader)
    except ValidationError as e:
        for message in validation_messages(e):
            st.error(message)
        return
    set_trip(trip)
    clear_review_widgets()
    st.success("여행 설정을 저장했습니다.")
    st.button("다음: 영수증 올리기 →", key="setup_next", on_click=go_to, args=("업로드",))
