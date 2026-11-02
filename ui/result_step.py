"""4단계: 사람별 정산 표, 송금 메시지, 결과 JSON 내려받기."""

import html

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.payment_message import build_message, format_won
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
    # 참석자가 비었거나 여행 밖 이름이면 compute_balances가 예외를 내므로 먼저 막는다.
    errors = readiness_errors(labeled_trip(trip))
    if errors:
        st.header("정산 전에 고칠 게 있어요", anchor=False)
        for error in errors:
            st.error(error)
        bottom_button("확인 화면으로 돌아가기", key="result_back", on_click=go_to, args=("검토",))
        return

    st.header("이렇게 나누면 돼요", anchor=False)
    balances = compute_balances(trip)
    st.html(summary_html(trip))
    _render_transfers(plan_transfers(balances), trip)
    st.subheader("사람별 정산", anchor=False)
    _render_people(balances, trip)
    with st.expander("표로 보기", icon=":material/table_rows:"):
        _render_table(balances, trip)
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
    # 위치 조회가 느려도 저장 버튼이 먼저 보이도록 맨 마지막에 그린다(버튼은 화면 아래 고정이다).
    render_map(trip)


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
    for b in balances:
        name = f"{b.name} (대표 {trip.leader})" if b.name == FUND_WALLET else b.name
        with st.container(
            border=True,
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        ):
            with st.container(width="content", gap=None):
                st.markdown(f"**{name}**")
                st.caption(f"낸 돈 {format_won(b.paid)}, 내 몫 {format_won(b.owed)}")
            with st.container(width="content", gap=None, horizontal_alignment="right"):
                if b.net > 0:
                    st.caption("받을 돈")
                    st.markdown(f"### :primary[{format_won(b.net)}]", anchors=False)
                elif b.net < 0:
                    st.caption("보낼 돈")
                    st.markdown(f"### {format_won(-b.net)}", anchors=False)
                else:
                    st.caption("주고받을 돈 없어요")
    if trip.mode == "fund":
        st.caption(f"회비형이라 낸 돈에 1인 회비 {format_won(trip.fund_per_person)}이 들어 있어요.")


def _signed_won(amount: int) -> str:
    return f"+{format_won(amount)}" if amount > 0 else format_won(amount)


def _net_color(net: int) -> str:
    """받을 돈은 강조색. 부호(+/-)도 함께 보여 색에만 기대지 않는다."""
    return f"color: {RECEIVE_COLOR}" if net > 0 else ""


def _render_table(balances: list[Balance], trip: Trip) -> None:
    rows = [{"이름": b.name, "낸 돈": b.paid, "내 몫": b.owed, "차액": b.net} for b in balances]
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
            "내 몫": st.column_config.NumberColumn(format="%,d원"),
        },
        alt=f"{trip.name} 사람별 낸 돈, 내 몫, 차액",
    )
    st.caption("차액이 +면 받을 돈, -면 보낼 돈이에요.")


def _is_leader_wallet(transfer: Transfer, trip: Trip) -> bool:
    """회비형에서 대표와 회비 지갑 사이 송금. 대표가 지갑을 들고 있어 자기 자신에게 보내는 꼴이다."""
    return trip.mode == "fund" and {transfer.sender, transfer.receiver} == {
        trip.leader,
        FUND_WALLET,
    }


def copy_text(transfer: Transfer, trip: Trip) -> str:
    """복사해서 보낼 글. 어디서 온 메시지인지 보이게 맨 앞에 서비스 이름을 붙인다."""
    return f"[{APP_NAME}]\n{build_message(transfer, trip)}"


def _render_transfers(transfers: list[Transfer], trip: Trip) -> None:
    st.subheader("보낼 돈", anchor=False)
    if not transfers:
        st.success("주고받을 돈이 없어요.")
        return
    st.caption("메시지를 복사해 단톡방에 보내 주세요.")
    for number, transfer in enumerate(transfers):
        amount = format_won(transfer.amount)
        if _is_leader_wallet(transfer, trip) and transfer.sender == trip.leader:
            st.info(f"대표가 직접 채울 금액: {amount} (대표 {trip.leader}님이 회비 지갑에 보태요)")
        elif _is_leader_wallet(transfer, trip):
            st.info(f"대표 몫 환급: 대표 {trip.leader}님이 회비 지갑에서 {amount}을 가져가요")
        else:
            with st.container(border=True):
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
                text = copy_text(transfer, trip)
                st.code(text, language=None, wrap_lines=True)
                copy_button(text, key=f"copy_{number}")
