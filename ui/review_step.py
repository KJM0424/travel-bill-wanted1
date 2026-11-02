"""3단계: 날짜별 결제 목록. 줄을 눌러 펼치면 참석자·금액·결제자 등을 고친다."""

from collections import Counter
from datetime import date, datetime, time
from itertools import groupby

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.expense_builder import UNKNOWN_MERCHANT, find_duplicates, sort_expenses
from core.payment_message import format_won
from core.schema import FUND_WALLET, Expense, Trip
from ui.layout import bottom_button
from ui.state import get_trip, go_to, init_widget, session, set_trip


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


CATEGORY_ICONS = {
    "food": "restaurant",
    "cafe": "local_cafe",
    "lodging": "hotel",
    "transport": "directions_car",
    "shopping": "shopping_bag",
    "activity": "attractions",
    "etc": "receipt_long",
}
WEEKDAYS = "월화수목금토일"
OPENED_KEY = "rv_opened"


def day_label(day: date | None) -> str:
    if day is None:
        return "날짜 모름"
    return f"{day.month}월 {day.day}일 {WEEKDAYS[day.weekday()]}요일"


def render_review() -> None:
    st.header("결제 내역을 확인해 주세요", anchor=False)
    trip = get_trip()
    # 합계는 위젯 값을 반영한 뒤에 채운다. 먼저 그리면 금액을 고친 직후 옛 합계가 보인다.
    summary = st.container()
    if not trip.expenses:
        st.info("아직 결제가 없어요. 영수증을 올리거나 아래에서 직접 추가해 주세요.")
    else:
        st.caption("결제를 누르면 함께한 사람과 금액을 고칠 수 있어요.")
    duplicated = _render_duplicates(trip)

    updated: list[Expense] = []
    for index, (day, group) in enumerate(groupby(trip.expenses, key=_expense_day)):
        head = st.container(
            key=f"day_head_{index}",
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="bottom",
        )
        rows = [_render_row(e, trip, e.expense_id in duplicated) for e in group]
        _fill_day_head(head, day, rows)
        updated.extend(rows)
    if updated != trip.expenses:
        # 날짜·시각을 고치면 순서가 바뀔 수 있다. 위젯 key는 결제 건 id라서 다시 정렬해도 값이 유지된다.
        set_trip(trip.model_copy(update={"expenses": sort_expenses(updated)}))
    _fill_summary(summary, updated)

    st.space("small")
    with st.expander("영수증 없는 지출 추가", icon=":material/add:"):
        _render_manual_form()
    bottom_button("정산하기", key="review_next", on_click=go_to, args=("정산",))


def _expense_day(e: Expense) -> date | None:
    return e.paid_at.date() if e.paid_at else None


def _active_total(expenses: list[Expense]) -> int:
    return sum(e.amount for e in expenses if not e.excluded)


def _fill_summary(summary: DeltaGenerator, expenses: list[Expense]) -> None:
    if not expenses:
        return
    count = sum(1 for e in expenses if not e.excluded)
    with summary.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="bottom"
    ):
        st.caption(f"정산할 결제 {count}건", width="content")
        st.markdown(f"### {format_won(_active_total(expenses))}", anchors=False, width="content")


def _fill_day_head(head: DeltaGenerator, day: date | None, rows: list[Expense]) -> None:
    head.markdown(day_label(day), width="content")
    head.caption(format_won(_active_total(rows)), width="content")


def _render_duplicates(trip: Trip) -> set[str]:
    """중복 의심 결제를 위에 한 번만 알리고, 해당 결제 id를 돌려준다(행에도 표시한다)."""
    by_id = {e.expense_id: e for e in trip.expenses}
    pairs = find_duplicates([e for e in trip.expenses if not e.excluded])
    if not pairs:
        return set()
    lines = []
    for first, _ in pairs:
        e = by_id[first]
        when = e.paid_at.strftime("%H:%M") + " " if e.paid_at and e.time_known else ""
        lines.append(f"{e.merchant_name} {when}결제가 두 번 있어요.")
    st.warning(
        " ".join(lines) + " 같은 결제라면 하나를 열어 '정산에서 빼기'를 켜 주세요.",
        title="중복 결제일 수 있어요",
        icon=":material/content_copy:",
    )
    return {eid for pair in pairs for eid in pair}


def _render_row(e: Expense, trip: Trip, duplicated: bool) -> Expense:
    """결제 한 줄. 줄을 누르면 참석자와 수정 칸이 펼쳐지고 다시 누르면 접힌다.

    바뀌었으면 고친 결제 건을 돌려준다.
    """
    eid = e.expense_id
    opened = eid in session().get(OPENED_KEY, set())
    with st.container(key=f"row_{eid}"):
        head = st.container(
            key=f"rh_{eid}", horizontal=True, vertical_alignment="center", gap="small"
        )
        notes = st.container(gap=None)
        changes = _render_editor(e, trip) if opened else {}
    updated = _apply(e, changes)
    _fill_row_head(head, updated, trip, opened)
    for warning in [*e.warnings, *(["같은 결제가 하나 더 있어요."] if duplicated else [])]:
        notes.caption(f":orange[:material/error: {warning}]")
    return updated


def who_joined(e: Expense, trip: Trip) -> str:
    if not e.participants:
        return "함께한 사람 없음"
    if sorted(e.participants) == sorted(trip.members):
        return f"{len(trip.members)}명 모두"
    return ", ".join(m for m in trip.members if m in e.participants)


def _fill_row_head(head: DeltaGenerator, e: Expense, trip: Trip, opened: bool) -> None:
    with head.container(key=f"ico_{e.expense_id}", width=40):
        st.markdown(f":material/{CATEGORY_ICONS.get(e.category, 'receipt_long')}:")
    with head.container(key=f"rt_{e.expense_id}", gap=None):
        st.markdown(f"~~{e.merchant_name}~~" if e.excluded else f"**{e.merchant_name}**")
        when = e.paid_at.strftime("%H:%M") if e.paid_at and e.time_known else "시간 모름"
        detail = f"{when}, {e.payer} 결제, {who_joined(e, trip)}"
        st.caption("정산에서 뺐어요" if e.excluded else detail)
    won = format_won(e.amount)
    head.markdown(f":gray[~~{won}~~]" if e.excluded else f"**{won}**", width="content")
    head.markdown(
        f":gray[:material/{'expand_less' if opened else 'expand_more'}:]", width="content"
    )
    # 줄 전체를 덮는 투명 버튼(ui/layout.py CSS). 화면 읽기 프로그램에는 이 이름으로 읽힌다.
    head.button(
        f"{e.merchant_name} {'접기' if opened else '펼치기'}",
        key=f"rv_open_{e.expense_id}",
        type="tertiary",
        on_click=_toggle_editor,
        args=(e.expense_id,),
    )


def _toggle_editor(eid: str) -> None:
    opened = set(session().get(OPENED_KEY, set()))
    if eid in opened:
        opened.discard(eid)
        # 다시 펼칠 때 결제 건의 최신 값으로 채우도록 수정 칸 값을 지운다.
        for key in [
            *(f"rv_{field}_{eid}" for field in EDIT_FIELDS),
            f"excl_{eid}",
            f"part_{eid}",
        ]:
            session().pop(key, None)
    else:
        opened.add(eid)
    session()[OPENED_KEY] = opened


EDIT_FIELDS = ("name", "amount", "date", "notime", "time", "addr", "payer")


def _render_editor(e: Expense, trip: Trip) -> dict:
    """펼친 행의 수정 칸. 위젯 값으로 만든 변경 내용을 돌려준다."""
    eid = e.expense_id
    _init_editor_widgets(e)
    payer_options = [*trip.members, *([FUND_WALLET] if trip.mode == "fund" else [])]
    if e.payer not in payer_options:
        payer_options.append(e.payer)
    init_widget(f"part_{eid}", [m for m in trip.members if m in e.participants])
    with st.container(key=f"edit_{eid}"):
        participants = st.pills(
            "함께한 사람",
            trip.members,
            selection_mode="multi",
            key=f"part_{eid}",
            help="함께하지 않은 사람은 눌러서 빼 주세요.",
        )
        name = st.text_input("가게 이름", key=f"rv_name_{eid}")
        amount = st.number_input("금액 (원)", min_value=0, step=100, key=f"rv_amount_{eid}")
        with st.container(horizontal=True, vertical_alignment="bottom"):
            day = st.date_input("날짜", key=f"rv_date_{eid}")
            no_time = st.session_state.get(f"rv_notime_{eid}", False)
            clock = st.time_input("시각", key=f"rv_time_{eid}", disabled=no_time)
        no_time = st.checkbox("시간 모름", key=f"rv_notime_{eid}")
        address = st.text_input("주소", key=f"rv_addr_{eid}", help="여행 경로 지도에 쓰여요.")
        payer = st.selectbox("결제한 사람", payer_options, key=f"rv_payer_{eid}")
        excluded = st.toggle("정산에서 빼기", key=f"excl_{eid}")
    # '시간 모름'을 풀어도 시각을 고르기 전까지는 시간을 모르는 것으로 둔다(00:00으로 정하지 않는다).
    time_known = not no_time and clock is not None
    paid_at = datetime.combine(day, clock if time_known else time(0)) if day else None
    return {
        "participants": list(participants),
        "merchant_name": name.strip() or UNKNOWN_MERCHANT,
        "merchant_address": address.strip() or None,
        "paid_at": paid_at,
        "time_known": paid_at is not None and time_known,
        "amount": int(amount),
        "payer": payer,
        "excluded": excluded,
    }


def _apply(e: Expense, changes: dict) -> Expense:
    if all(getattr(e, field) == value for field, value in changes.items()):
        return e
    # model_copy는 얕은 복사라서 리스트는 새로 만든 것을 넘긴다.
    return e.model_copy(update=changes)


def _init_editor_widgets(e: Expense) -> None:
    eid = e.expense_id
    init_widget(f"rv_name_{eid}", e.merchant_name)
    init_widget(f"rv_amount_{eid}", e.amount)
    init_widget(f"rv_date_{eid}", e.paid_at.date() if e.paid_at else None)
    init_widget(f"rv_notime_{eid}", not e.time_known)
    init_widget(f"rv_time_{eid}", e.paid_at.time() if e.paid_at and e.time_known else None)
    init_widget(f"rv_addr_{eid}", e.merchant_address or "")
    init_widget(f"rv_payer_{eid}", e.payer)
    init_widget(f"excl_{eid}", e.excluded)


def _render_manual_form() -> None:
    with st.form("manual_form", clear_on_submit=True, border=False):
        name_col, amount_col = st.columns([3, 2])
        merchant = name_col.text_input("내용", key="manual_merchant", placeholder="주차비")
        amount = amount_col.number_input("금액 (원)", min_value=0, step=100, key="manual_amount")
        date_col, time_col = st.columns(2)
        day = date_col.date_input("날짜 (선택)", value=None, key="manual_date")
        clock = time_col.time_input("시각 (선택)", value=None, key="manual_time")
        submitted = st.form_submit_button(
            "추가하기", key="manual_add", icon=":material/add:", width="stretch"
        )

    if not submitted:
        return
    if not merchant.strip():
        st.error("무엇에 쓴 돈인지 적어 주세요.")
        return
    if amount <= 0:
        st.error("금액은 0원보다 커야 해요.")
        return
    paid_at = datetime.combine(day, clock or time(0)) if day else None
    set_trip(add_manual_expense(get_trip(), merchant, int(amount), paid_at, clock is not None))
    st.rerun()
