"""1단계: 여행 설정 (참석자, 대표, 정산 방식, 송금 정보)."""

from datetime import date

import streamlit as st
from pydantic import ValidationError

from core.payment_message import BANKS, clean_account_number, match_bank, split_old_account
from core.schema import PayoutInfo, Trip
from core.trip_story import trip_length_label
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
LINK_FIELDS = [
    ("toss_link", "토스 송금 링크"),
    ("kakaopay_link", "카카오페이 송금 링크"),
]
PAYOUT_FIELDS = ["bank", "account_number", "account_holder", *(f for f, _ in LINK_FIELDS)]
ACCOUNT_PAIR_ERROR = "은행과 계좌번호를 함께 적어 주세요."


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
    st.header("여행 정보를 알려 주세요", anchor=False)
    st.caption("질문 네 가지에 답하면 영수증을 올릴 수 있어요.")
    trip = get_trip()
    _init_from_trip(trip)

    # 질문 하나에 카드 하나(ui/layout.py의 .st-key-sec_ CSS). 무엇을 채워야 하는지 한눈에 보이게 한다.
    with _section("sec_trip", "어디로 다녀왔나요?"):
        st.text_input("여행 이름 (선택)", key="setup_name", placeholder="제주 2박 3일")
        with st.container(horizontal=True):
            st.date_input("가는 날", key="setup_start")
            st.date_input("오는 날", key="setup_end")
        _render_trip_length(session()["setup_start"], session()["setup_end"])

    with _section("sec_people", "누구와 함께 갔나요?"):
        st.text_input(
            "함께한 사람",
            key="setup_members",
            placeholder="이름을 쉼표로 나눠 적어 주세요",
            help="예: 민수, 지영, 철수. 다 적고 Enter를 눌러 주세요.",
        )
        names = list(dict.fromkeys(n for n in parse_members(session()["setup_members"]) if n))
        if session().get("setup_leader") not in names:
            # 값을 지우기만 하면 화면에는 빈 선택이나 빠진 사람이 남는다.
            session()["setup_leader"] = names[0] if names else None
        if names:
            st.markdown(f"**{len(names)}명** " + " ".join(f":gray-badge[{n}]" for n in names))
            st.pills("총무", names, key="setup_leader")
            st.caption("돈을 모으거나 대신 낸 사람이에요. 보통 정산금을 받아요.")
        else:
            st.caption("이름을 적으면 여기서 총무를 고를 수 있어요.")

    with _section("sec_mode", "어떻게 정산할까요?"):
        st.segmented_control(
            "정산 방식",
            list(MODE_BY_LABEL),
            key="setup_mode",
            required=True,
            width="stretch",
            label_visibility="collapsed",
        )
        st.caption(MODE_HELP[MODE_BY_LABEL[session()["setup_mode"]]])
        if session()["setup_mode"] == MODE_LABELS["fund"]:
            st.number_input("1인 회비 (원)", min_value=0, step=10000, key="setup_fee")

    leader = session().get("setup_leader")
    if leader:
        # 총무는 돈을 모으거나 대신 낸 사람이라 대부분 받는 쪽이다. 계좌를 접지 않고 바로 받는다.
        with _section("sec_account", f"{leader}님 계좌를 알려 주세요"):
            st.caption("송금 메시지에 들어가고, 정산 화면에서 은행과 계좌번호만 복사할 수 있어요.")
            _account_inputs(leader)

    with st.expander("송금 링크·다른 사람 계좌 (선택)", icon=":material/account_balance:"):
        if not names:
            st.caption("함께한 사람을 먼저 적어 주세요.")
        else:
            st.caption("받을 사람만 적으면 송금 메시지에 함께 들어가요.")
        for name in names:
            st.markdown(f"**{name}**")
            if name != leader:
                _account_inputs(name)
            for field, label in LINK_FIELDS:
                key = _payout_key(name, field)
                init_widget(key, "")
                st.text_input(label, key=key)

    if bottom_button("다음", key="setup_save"):
        _save(trip, names)


def _section(key: str, title: str):
    box = st.container(key=key)
    box.markdown(f"#### {title}", anchors=False)
    return box


def _render_trip_length(start: date | None, end: date | None) -> None:
    if not start or not end:
        return
    if end < start:
        st.caption(":red[오는 날이 가는 날보다 빨라요.]")
        return
    st.markdown(f":green-badge[{trip_length_label(start, end)}]")


def _account_inputs(name: str) -> None:
    bank_key = _payout_key(name, "bank")
    init_widget(bank_key, None)
    current = session().get(bank_key)
    # 직접 적은 은행이나 예전 파일의 은행 이름도 고른 값으로 보여야 한다.
    options = [*BANKS, *([current] if current and current not in BANKS else [])]
    with st.container(horizontal=True):
        st.selectbox(
            "은행",
            options,
            key=bank_key,
            placeholder="은행 고르기",
            accept_new_options=True,
        )
        number_key = _payout_key(name, "account_number")
        init_widget(number_key, "")
        st.text_input("계좌번호", key=number_key, placeholder="3333-01-1234567")
    holder_key = _payout_key(name, "account_holder")
    init_widget(holder_key, "")
    st.text_input("예금주", key=holder_key, placeholder=name)


def _payout_fields(info: PayoutInfo) -> dict[str, str | None]:
    """화면 칸에 채울 값. 예전 한 칸 형식 계좌는 은행·번호·예금주로 나눠 채운다."""
    fields = {f: getattr(info, f) for f in PAYOUT_FIELDS}
    old = split_old_account(info.bank_account) if info.bank_account else None
    if old and not info.account_number:
        bank, number, holder = old
        fields |= {"bank": match_bank(bank), "account_number": number, "account_holder": holder}
    return fields


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
        for field, value in _payout_fields(info).items():
            init_widget(_payout_key(name, field), value if field == "bank" else value or "")


def _payout_key(name: str, field: str) -> str:
    return f"{SETUP_WIDGET_PREFIX}pay_{name}_{field}"


def _collect_payout(names: list[str]) -> tuple[dict[str, dict[str, str | None]], list[str]]:
    """(사람별 송금 정보, 오류 문장). 계좌는 은행과 번호가 함께 있어야 하고 번호 형식이 맞아야 한다."""
    payout, errors = {}, []
    for name in names:
        info = {
            f: (session().get(_payout_key(name, f)) or "").strip() or None for f in PAYOUT_FIELDS
        }
        if info["bank"] or info["account_number"]:
            if not (info["bank"] and info["account_number"]):
                errors.append(f"{name}: {ACCOUNT_PAIR_ERROR}")
            else:
                try:
                    info["account_number"] = clean_account_number(info["account_number"])
                except ValueError as e:
                    errors.append(f"{name}: {e}")
        if any(info.values()):
            payout[name] = info
    return payout, errors


def _save(previous: Trip | None, names: list[str]) -> None:
    state = session()
    payout, errors = _collect_payout(names)
    for message in errors:
        st.error(message)
    if errors:
        return
    mode = MODE_BY_LABEL[state["setup_mode"]]
    data = {
        "name": state["setup_name"].strip() or "여행",
        "members": parse_members(state["setup_members"]),
        "leader": state.get("setup_leader") or "",
        "mode": mode,
        "fund_per_person": int(state.get("setup_fee") or 0) if mode == "fund" else 0,
        "start_date": state["setup_start"],
        "end_date": state["setup_end"],
        "payout": payout,
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
