"""3단계: 결제 건을 고치고, 결제자와 참석자를 정하고, 영수증 없는 지출을 추가한다."""

from collections import Counter
from datetime import datetime, time

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.expense_builder import UNKNOWN_MERCHANT, find_duplicates, sort_expenses
from core.payment_message import format_won
from core.schema import FUND_WALLET, Expense, Trip
from ui.state import get_trip, go_to, init_widget, set_trip


def default_payer(trip: Trip) -> str:
    return FUND_WALLET if trip.mode == "fund" else trip.leader


def add_manual_expense(
    trip: Trip,
    merchant: str,
    amount: int,
    paid_at: datetime | None,
    time_known: bool = False,
) -> Trip:
    """결제자는 기본값(대표 또는 회비 지갑), 참석자는 전원으로 수동 결제 건을 더한다."""
    used = {e.expense_id for e in trip.expenses}
    n = 1
    while f"manual-{n}" in used:
        n += 1
    expense = Expense(
        expense_id=f"manual-{n}",
        source="manual",
        merchant_name=merchant.strip(),
        paid_at=paid_at,
        time_known=time_known and paid_at is not None,
        amount=amount,
        payer=default_payer(trip),
        participants=list(trip.members),
    )
    return trip.model_copy(update={"expenses": sort_expenses([*trip.expenses, expense])})


def expense_labels(trip: Trip) -> dict[str, str]:
    """화면과 오류 메시지에 쓸 이름. 같은 상호가 여러 건이면 순번과 시각을 붙인다."""
    counts = Counter(e.merchant_name for e in trip.expenses)
    labels = {}
    for number, e in enumerate(trip.expenses, start=1):
        if counts[e.merchant_name] == 1:
            labels[e.expense_id] = e.merchant_name
            continue
        detail = f"#{number}"
        if e.paid_at is not None:
            detail += " " + e.paid_at.strftime("%m/%d %H:%M" if e.time_known else "%m/%d")
        labels[e.expense_id] = f"{e.merchant_name} ({detail})"
    return labels


def render_review() -> None:
    st.header("검토·참석자 체크")
    trip = get_trip()
    if not trip.expenses:
        st.info(
            "아직 결제 건이 없습니다. 영수증을 올리거나 아래에서 수동으로 추가하세요.",
            icon=":material/receipt_long:",
        )

    labels = expense_labels(trip)
    _render_duplicates(trip, labels)
    updated = [
        _render_card(number, e, trip, labels[e.expense_id])
        for number, e in enumerate(trip.expenses, start=1)
    ]
    if updated != trip.expenses:
        # 날짜·시각을 고치면 순서가 바뀔 수 있다. 위젯 key는 결제 건 id라서 다시 정렬해도 값이 유지된다.
        set_trip(trip.model_copy(update={"expenses": sort_expenses(updated)}))

    _render_manual_form()
    st.button(
        "다음 단계: 정산",
        key="review_next",
        type="primary",
        icon=":material/calculate:",
        on_click=go_to,
        args=("정산",),
    )


def _render_duplicates(trip: Trip, labels: dict[str, str]) -> None:
    active = [e for e in trip.expenses if not e.excluded]
    for first, second in find_duplicates(active):
        st.warning(
            f"중복 의심: '{labels[first]}'와 '{labels[second]}'의 금액이 같고 10분 안에 "
            "결제했습니다. 같은 결제라면 하나를 '정산에서 제외'로 체크하세요."
        )


def _render_card(number: int, e: Expense, trip: Trip, label: str) -> Expense:
    """카드 하나를 그리고, 위젯 값이 바뀌었으면 고친 결제 건을 돌려준다."""
    eid = e.expense_id
    _init_card_widgets(e, trip)
    payer_options = [*trip.members, *([FUND_WALLET] if trip.mode == "fund" else [])]
    if e.payer not in payer_options:
        payer_options.append(e.payer)

    with st.container(border=True):
        # 머리줄은 위젯 값을 읽은 뒤에 채운다. 먼저 그리면 금액을 고친 직후 옛 금액이 보인다.
        head = st.container(
            horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
        )
        for warning in e.warnings:
            st.warning(warning)

        name_col, amount_col = st.columns([3, 2])
        name = name_col.text_input("상호", key=f"rv_name_{eid}")
        amount = amount_col.number_input("금액 (원)", min_value=0, step=100, key=f"rv_amount_{eid}")
        date_col, time_col, unknown_col = st.columns([2, 2, 1], vertical_alignment="bottom")
        day = date_col.date_input("날짜", key=f"rv_date_{eid}")
        no_time = unknown_col.checkbox("시간 모름", key=f"rv_notime_{eid}")
        clock = time_col.time_input("시각", key=f"rv_time_{eid}", disabled=no_time)
        address = st.text_input("주소", key=f"rv_addr_{eid}")
        payer = st.selectbox("결제자", payer_options, key=f"rv_payer_{eid}")

        st.caption("참석자 (빠진 사람만 해제)")
        # 사람 수만큼 칸을 나누면 많을 때 이름이 잘린다. 가로로 놓고 넘치면 다음 줄로 보낸다.
        with st.container(horizontal=True, gap="medium"):
            participants = [m for m in trip.members if st.checkbox(m, key=f"part_{eid}_{m}")]
        excluded = st.checkbox("정산에서 제외", key=f"excl_{eid}")
        _render_card_head(head, number, e, label, int(amount), excluded)

    # '시간 모름'을 풀어도 시각을 고르기 전까지는 시간을 모르는 것으로 둔다(00:00으로 정하지 않는다).
    time_known = not no_time and clock is not None
    paid_at = datetime.combine(day, clock if time_known else time(0)) if day else None
    changes = {
        "merchant_name": name.strip() or UNKNOWN_MERCHANT,
        "merchant_address": address.strip() or None,
        "paid_at": paid_at,
        "time_known": paid_at is not None and time_known,
        "amount": int(amount),
        "payer": payer,
        "participants": participants,
        "excluded": excluded,
    }
    if all(getattr(e, field) == value for field, value in changes.items()):
        return e
    # model_copy는 얕은 복사라서 리스트는 새로 만든 것을 넘긴다.
    return e.model_copy(update={**changes, "participants": list(participants)})


def _render_card_head(
    head: DeltaGenerator, number: int, e: Expense, label: str, amount: int, excluded: bool
) -> None:
    """영수증처럼 이름은 왼쪽, 금액은 오른쪽에 둔다."""
    # 같은 상호가 여러 건이면 label에 이미 순번이 들어 있다.
    title = label if label != e.merchant_name else f"#{number} {label}"
    source = ":blue-badge[AI 인식]" if e.source == "ai" else ":gray-badge[수동 입력]"
    badges = source + (" :red-badge[정산 제외]" if excluded else "")
    head.markdown(f"**{title}** {badges}", width="content")
    won = format_won(amount)
    head.markdown(f"~~{won}~~" if excluded else f"**{won}**", width="content")


def _init_card_widgets(e: Expense, trip: Trip) -> None:
    eid = e.expense_id
    init_widget(f"rv_name_{eid}", e.merchant_name)
    init_widget(f"rv_amount_{eid}", e.amount)
    init_widget(f"rv_date_{eid}", e.paid_at.date() if e.paid_at else None)
    init_widget(f"rv_notime_{eid}", not e.time_known)
    init_widget(f"rv_time_{eid}", e.paid_at.time() if e.paid_at and e.time_known else None)
    init_widget(f"rv_addr_{eid}", e.merchant_address or "")
    init_widget(f"rv_payer_{eid}", e.payer)
    for m in trip.members:
        init_widget(f"part_{eid}_{m}", m in e.participants)
    init_widget(f"excl_{eid}", e.excluded)


def _render_manual_form() -> None:
    st.subheader("영수증 없는 지출 추가", icon=":material/edit_note:")
    with st.form("manual_form", clear_on_submit=True):
        name_col, amount_col = st.columns([3, 2])
        merchant = name_col.text_input("상호·내용", key="manual_merchant", placeholder="주차비")
        amount = amount_col.number_input("금액 (원)", min_value=0, step=100, key="manual_amount")
        date_col, time_col = st.columns(2)
        day = date_col.date_input("날짜 (선택)", value=None, key="manual_date")
        clock = time_col.time_input("시각 (선택)", value=None, key="manual_time")
        submitted = st.form_submit_button("추가", key="manual_add", icon=":material/add:")

    if not submitted:
        return
    if not merchant.strip():
        st.error("상호나 내용을 입력하세요.")
        return
    if amount <= 0:
        st.error("금액을 0원보다 크게 입력하세요.")
        return
    paid_at = datetime.combine(day, clock or time(0)) if day else None
    set_trip(add_manual_expense(get_trip(), merchant, int(amount), paid_at, clock is not None))
    st.rerun()
