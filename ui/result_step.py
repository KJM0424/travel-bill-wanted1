"""4단계: 사람별 정산 표, 송금 메시지, 결과 JSON 내려받기."""

import html

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.payment_message import account_copy_text, build_message, format_won, payout_owner
from core.schema import FUND_WALLET, Trip
from core.settlement import Balance, Transfer, compute_balances, plan_transfers, readiness_errors
from ui.branding import APP_NAME
from ui.copy_button import copy_button
from ui.layout import bottom, bottom_button
from ui.map_view import render_map
from ui.review_step import expense_labels
from ui.state import get_trip, go_to

IMPORT_ERROR = "불러올 수 없는 파일이에요. 정산 단계에서 저장한 파일인지 확인해 주세요."
# .streamlit/config.toml의 primaryColor와 같은 값이다.
RECEIVE_COLOR = "#17654C"
RESULT_VIEWS = ["보낼 돈", "사람별 정산", "여행 돌아보기"]


def export_trip(trip: Trip) -> bytes:
    return trip.model_dump_json(indent=2).encode("utf-8")


def import_trip(data: bytes) -> Trip:
    try:
        trip = Trip.model_validate_json(data)
    except (ValidationError, ValueError):
        raise ValueError(IMPORT_ERROR) from None
    # 결제 건 id는 위젯 key가 되므로 겹치면 화면이 멈춘다.
    ids = [e.expense_id for e in trip.expenses]
    if len(ids) != len(set(ids)):
        raise ValueError(IMPORT_ERROR)
    return trip


def labeled_trip(trip: Trip) -> Trip:
    """같은 상호가 여러 건이면 순번·시각을 붙인 이름으로 바꾼 사본. 오류 메시지 구분용이다."""
    labels = expense_labels(trip)
    expenses = [e.model_copy(update={"merchant_name": labels[e.expense_id]}) for e in trip.expenses]
    return trip.model_copy(update={"expenses": expenses})


def render_result() -> None:
    trip = get_trip()
    # 함께한 사람이 비었거나 여행 밖 이름이면 compute_balances가 예외를 내므로 먼저 막는다.
    errors = readiness_errors(labeled_trip(trip))
    if errors:
        st.header("정산 전에 고칠 게 있어요", anchor=False)
        for error in errors:
            st.error(error)
        bottom_button("결제 내역으로 돌아가기", key="result_back", on_click=go_to, args=("검토",))
        return

    st.header("이렇게 나누면 돼요", anchor=False)
    balances = compute_balances(trip)
    # 한 화면에 다 쌓으면 길어서, 위의 버튼으로 하나씩 본다. 지도는 열 때만 위치를 찾는다.
    view = st.segmented_control(
        "보기",
        RESULT_VIEWS,
        default=RESULT_VIEWS[0],
        key="result_view",
        required=True,
        width="stretch",
        label_visibility="collapsed",
    )
    if view == "보낼 돈":
        _render_transfers(plan_transfers(balances), trip)
    elif view == "사람별 정산":
        st.html(summary_html(trip))
        _render_people(balances, trip)
        with st.expander("표로 보기", icon=":material/table_rows:"):
            _render_table(balances, trip)
    else:
        render_map(trip)
    bottom().download_button(
        "정산 파일 저장하기",
        export_trip(trip),
        file_name=f"{trip.name}-정산.json",
        mime="application/json",
        key="result_download",
        type="primary",
        width="stretch",
        icon=":material/download:",
        help="저장한 파일은 시작 화면에서 다시 불러와 이어서 고칠 수 있어요.",
    )


def summary_html(trip: Trip) -> str:
    """영수증 한 장처럼 생긴 요약. 여행 이름은 사용자가 적은 값이라 이스케이프한다."""
    active = [e for e in trip.expenses if not e.excluded]
    total = sum(e.amount for e in active)
    period = f"{trip.start_date:%m.%d} ~ {trip.end_date:%m.%d}"
    rows = [
        ("결제", f"{len(active)}건"),
        ("함께한 사람", f"{len(trip.members)}명"),
        ("1인 평균", format_won(round(total / len(trip.members)))),
    ]
    if trip.mode == "fund":
        rows.append(("1인 회비", format_won(trip.fund_per_person)))
    items = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
    return (
        '<div class="tv-slip">'
        f'<p class="tv-label">{html.escape(trip.name)} <span>{period}</span></p>'
        f'<p class="tv-total">{format_won(total)}</p>'
        f"<dl>{items}</dl></div>"
    )


def _render_people(balances: list[Balance], trip: Trip) -> None:
    """사람마다 카드 하나. 보낼 돈·받을 돈을 크게 보여 준다."""
    for index, b in enumerate(balances):
        name = f"{b.name} (총무 {trip.leader})" if b.name == FUND_WALLET else b.name
        with st.container(
            key=f"pc_{index}",
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        ):
            with st.container(width="content", gap=None):
                st.markdown(f"**{name}**")
                st.caption(f"낸 돈 {format_won(b.paid)}, 부담할 돈 {format_won(b.owed)}")
            with st.container(width="content", gap=None, horizontal_alignment="right"):
                if b.net > 0:
                    st.caption("받을 돈")
                    st.markdown(f"### :primary[{format_won(b.net)}]", anchors=False)
                elif b.net < 0:
                    st.caption("보낼 돈")
                    st.markdown(f"### {format_won(-b.net)}", anchors=False)
                else:
                    st.caption("주고받을 돈이 없어요")
    if trip.mode == "fund":
        st.caption(f"회비형이라 낸 돈에 1인 회비 {format_won(trip.fund_per_person)}이 들어 있어요.")


def _signed_won(amount: int) -> str:
    return f"+{format_won(amount)}" if amount > 0 else format_won(amount)


def _net_color(net: int) -> str:
    """받을 돈은 강조색. 부호(+/-)도 함께 보여 색에만 기대지 않는다."""
    return f"color: {RECEIVE_COLOR}" if net > 0 else ""


def _render_table(balances: list[Balance], trip: Trip) -> None:
    rows = [{"이름": b.name, "낸 돈": b.paid, "부담할 돈": b.owed, "차액": b.net} for b in balances]
    # 숫자 칸으로 두어 오른쪽 정렬된다.
    styled = (
        pd.DataFrame(rows)
        .style.map(_net_color, subset=["차액"])
        .format(_signed_won, subset=["차액"])
    )
    st.dataframe(
        styled,
        hide_index=True,
        column_config={
            "낸 돈": st.column_config.NumberColumn(format="%,d원"),
            "부담할 돈": st.column_config.NumberColumn(format="%,d원"),
        },
        alt=f"{trip.name} 사람별 낸 돈, 부담할 돈, 차액",
    )
    st.caption("차액이 +면 받을 돈, -면 보낼 돈이에요.")


def _is_leader_wallet(transfer: Transfer, trip: Trip) -> bool:
    """회비형에서 총무와 회비 지갑 사이 송금. 총무가 지갑을 들고 있어 자기 자신에게 보내는 꼴이다."""
    return trip.mode == "fund" and {transfer.sender, transfer.receiver} == {
        trip.leader,
        FUND_WALLET,
    }


def copy_text(transfer: Transfer, trip: Trip) -> str:
    """복사해서 보낼 글. 어디서 온 메시지인지 보이게 맨 앞에 서비스 이름을 붙인다."""
    return f"[{APP_NAME}]\n{build_message(transfer, trip)}"


def transfer_copies(transfer: Transfer, trip: Trip) -> list[tuple[str, str]]:
    """송금 카드의 복사 버튼들: (버튼 이름, 복사할 글). 받는 사람 계좌가 있으면 계좌 복사를 더한다."""
    copies = [("메시지 복사", copy_text(transfer, trip))]
    account = account_copy_text(trip.payout.get(payout_owner(transfer, trip)))
    if account:
        copies.append(("계좌 복사", account))
    return copies


def _render_transfers(transfers: list[Transfer], trip: Trip) -> None:
    if not transfers:
        with st.container(key="empty_state"):
            st.markdown("### :primary[:material/handshake:]")
            st.markdown("#### 모두 쓴 만큼 냈어요")
            st.caption("주고받을 돈이 없어요. 정산 파일만 저장해 두면 돼요.")
        return
    st.caption("메시지를 복사해 단톡방에 보내 주세요.")
    for number, transfer in enumerate(transfers):
        amount = format_won(transfer.amount)
        if _is_leader_wallet(transfer, trip) and transfer.sender == trip.leader:
            st.info(f"회비가 {amount} 모자라요. 총무 {trip.leader}님이 채워 주세요.")
        elif _is_leader_wallet(transfer, trip):
            st.info(
                f"회비가 남았어요. 총무 {trip.leader}님 몫 {amount}은 남은 회비에서 가져가면 돼요."
            )
        else:
            with st.container(key=f"tr_{number}"):
                with st.container(
                    horizontal=True,
                    horizontal_alignment="distribute",
                    vertical_alignment="center",
                ):
                    st.markdown(
                        f"**{transfer.sender}** :gray[:material/arrow_forward:] "
                        f"**{transfer.receiver}**",
                        width="content",
                    )
                    st.markdown(f"### {amount}", anchors=False, width="content")
                copies = transfer_copies(transfer, trip)
                st.code(copies[0][1], language=None, wrap_lines=True)
                with st.container(horizontal=True):
                    for index, (label, text) in enumerate(copies):
                        copy_button(text, key=f"copy_{number}_{index}", label=label)
