"""1단계: 여행 설정 (참석자, 대표, 정산 방식, 송금 정보)."""

from datetime import date

import streamlit as st
from pydantic import ValidationError

from core.schema import Trip
from ui.result_step import import_trip
from ui.state import (
    SETUP_WIDGET_PREFIX,
    add_members_to_expenses,
    clear_review_widgets,
    clear_upload_outcome,
    clear_widgets,
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
# 저장 버튼은 위젯 상태를 지우면 안 된다.
SETUP_BUTTON_KEYS = ("setup_save", "setup_next")
PAYOUT_FIELDS = [
    ("bank_account", "계좌 (은행 계좌번호 예금주)"),
    ("toss_link", "토스 송금 링크"),
    ("kakaopay_link", "카카오페이 송금 링크"),
]


def parse_members(text: str) -> list[str]:
    """쉼표로 구분한 이름. 끝 쉼표("A, B,")는 허용하고, 사이의 빈 칸은 그대로 두어 검증에서 막는다."""
    names = [name.strip() for name in text.split(",")]
    while names and not names[-1]:
        names.pop()
    return names


def load_trip_file(data: bytes) -> str | None:
    """내려받았던 결과 JSON으로 여행을 바꾼다. 실패하면 오류 문장을 돌려준다."""
    try:
        trip = import_trip(data)
    except ValueError as e:
        return str(e)
    set_trip(trip)
    # 설정·검토 위젯을 비워야 새 여행 값으로 다시 채워진다.
    clear_widgets([SETUP_WIDGET_PREFIX], keep=SETUP_BUTTON_KEYS)
    clear_review_widgets()
    clear_upload_outcome()
    return None


def render_setup() -> None:
    st.header("1. 여행 설정")
    _render_import()
    trip = get_trip()
    _init_from_trip(trip)

    st.text_input("여행 이름", key="setup_name", placeholder="제주 2박 3일")
    start_col, end_col = st.columns(2)
    start_col.date_input("시작일", key="setup_start")
    end_col.date_input("종료일", key="setup_end")
    st.text_input("참석자 (쉼표로 구분)", key="setup_members", placeholder="민수, 지영, 철수")

    names = list(dict.fromkeys(n for n in parse_members(session()["setup_members"]) if n))
    if session().get("setup_leader") not in names:
        # 값을 지우기만 하면 서버는 첫 사람을 고르지만 화면에는 빈 칸이나 빠진 사람이 남는다.
        session()["setup_leader"] = names[0] if names else None
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


def _render_import() -> None:
    uploaded = st.file_uploader("저장한 정산 파일(JSON) 불러오기", type=["json"], key="import_file")
    # 업로더는 파일을 계속 들고 있으므로 같은 파일을 매번 다시 불러오지 않게 한다.
    if uploaded is None or session().get("imported_file_id") == uploaded.file_id:
        return
    session()["imported_file_id"] = uploaded.file_id
    error = load_trip_file(uploaded.getvalue())
    if error:
        st.error(error)
    else:
        st.success("정산 파일을 불러왔습니다.")


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
    before = previous.members if previous else trip.members
    added = [m for m in trip.members if m not in before]
    removed = [m for m in before if m not in trip.members]
    if added:
        trip = add_members_to_expenses(trip, added)
    set_trip(trip)
    clear_review_widgets()
    st.success("여행 설정을 저장했습니다.")
    count = len(trip.expenses)
    if count and added:
        st.info(
            f"{', '.join(added)}님을 기존 결제 건 {count}개의 참석자로 추가했습니다. "
            "빠진 결제 건은 검토 단계에서 해제하세요."
        )
    if count and removed:
        st.info(f"{', '.join(removed)}님을 모든 결제 건의 참석자·결제자에서 뺐습니다.")
    st.button("다음: 영수증 올리기 →", key="setup_next", on_click=go_to, args=("업로드",))
