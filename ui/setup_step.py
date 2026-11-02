"""1단계: 여행 설정 (참석자, 대표, 정산 방식, 송금 정보)."""

from datetime import date

import streamlit as st
from pydantic import ValidationError

from core.schema import Trip
from ui.layout import bottom_button, flash
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
MODE_HELP = {
    "prepaid": "각자 결제하고 여행이 끝난 뒤 나눠요.",
    "fund": "회비를 먼저 모아 쓰고, 남거나 모자란 돈을 나눠요.",
}
# 저장 버튼은 위젯 상태를 지우면 안 된다.
SETUP_BUTTON_KEYS = ("setup_save",)
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
    st.header("어떤 여행이었나요?", anchor=False)
    trip = get_trip()
    _init_from_trip(trip)

    st.text_input("여행 이름", key="setup_name", placeholder="제주 2박 3일")
    with st.container(horizontal=True):
        st.date_input("가는 날", key="setup_start")
        st.date_input("오는 날", key="setup_end")

    st.space("small")
    st.subheader("누구와 갔나요?", anchor=False)
    st.text_input(
        "함께한 사람",
        key="setup_members",
        placeholder="민수, 지영, 철수",
        help="쉼표로 나눠 적고 Enter를 눌러 주세요.",
    )
    names = list(dict.fromkeys(n for n in parse_members(session()["setup_members"]) if n))
    if session().get("setup_leader") not in names:
        # 값을 지우기만 하면 화면에는 빈 선택이나 빠진 사람이 남는다.
        session()["setup_leader"] = names[0] if names else None
    if names:
        st.pills("총무", names, key="setup_leader", help="돈을 모으거나 대신 낸 사람이에요.")
    else:
        st.caption("이름을 적으면 여기서 총무를 고를 수 있어요.")

    st.space("small")
    st.segmented_control(
        "정산 방식", list(MODE_BY_LABEL), key="setup_mode", required=True, width="stretch"
    )
    st.caption(MODE_HELP[MODE_BY_LABEL[session()["setup_mode"]]])
    if session()["setup_mode"] == MODE_LABELS["fund"]:
        st.number_input("1인 회비 (원)", min_value=0, step=10000, key="setup_fee")

    with st.expander("돈 받을 계좌·송금 링크 (선택)", icon=":material/account_balance:"):
        if not names:
            st.caption("함께한 사람을 먼저 적어 주세요.")
        else:
            st.caption("받을 사람만 적으면 송금 메시지에 함께 들어가요.")
        for name in names:
            st.markdown(f"**{name}**")
            for field, label in PAYOUT_FIELDS:
                key = _payout_key(name, field)
                init_widget(key, "")
                st.text_input(label, key=key)

    if bottom_button("다음", key="setup_save"):
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
    before = previous.members if previous else trip.members
    added = [m for m in trip.members if m not in before]
    removed = [m for m in before if m not in trip.members]
    if added:
        trip = add_members_to_expenses(trip, added)
    set_trip(trip)
    clear_review_widgets()
    # 안내는 다음 화면 위에 보여 준다.
    count = len(trip.expenses)
    if count and added:
        flash(
            "info",
            f"{', '.join(added)}님을 결제 {count}건의 참석자로 추가했어요. "
            "빠진 결제는 확인 단계에서 체크를 풀어 주세요.",
        )
    if count and removed:
        flash("info", f"{', '.join(removed)}님을 모든 결제의 참석자·결제자에서 뺐어요.")
    go_to("업로드")
    st.rerun()
