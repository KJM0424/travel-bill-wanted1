"""4단계: 사람별 정산 표, 송금 메시지, 결과 JSON 내려받기."""

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.payment_message import build_message, format_won
from core.schema import FUND_WALLET, Trip
from core.settlement import Balance, Transfer, compute_balances, plan_transfers, readiness_errors
from ui.review_step import expense_labels
from ui.state import get_trip, go_to

IMPORT_ERROR = "불러올 수 없는 파일입니다."


def export_trip(trip: Trip) -> bytes:
    return trip.model_dump_json(indent=2).encode("utf-8")


def import_trip(data: bytes) -> Trip:
    try:
        return Trip.model_validate_json(data)
    except (ValidationError, ValueError):
        raise ValueError(IMPORT_ERROR) from None


def labeled_trip(trip: Trip) -> Trip:
    """같은 상호가 여러 건이면 순번·시각을 붙인 이름으로 바꾼 사본. 오류 메시지 구분용이다."""
    labels = expense_labels(trip)
    expenses = [e.model_copy(update={"merchant_name": labels[e.expense_id]}) for e in trip.expenses]
    return trip.model_copy(update={"expenses": expenses})


def render_result() -> None:
    st.header("4. 정산 결과")
    trip = get_trip()
    # 참석자가 비었거나 여행 밖 이름이면 compute_balances가 예외를 내므로 먼저 막는다.
    errors = readiness_errors(labeled_trip(trip))
    if errors:
        for error in errors:
            st.error(error)
        st.button("검토로 돌아가기", key="result_back", on_click=go_to, args=("검토",))
        return

    balances = compute_balances(trip)
    _render_table(balances, trip)
    _render_transfers(plan_transfers(balances), trip)
    st.download_button(
        "결과 JSON 내려받기",
        export_trip(trip),
        file_name=f"{trip.name}-정산.json",
        mime="application/json",
        key="result_download",
    )
    st.caption("내려받은 파일은 설정 단계에서 다시 불러올 수 있습니다.")


def _signed_won(amount: int) -> str:
    return f"+{format_won(amount)}" if amount > 0 else format_won(amount)


def _render_table(balances: list[Balance], trip: Trip) -> None:
    rows = [
        {
            "이름": b.name,
            "낸 돈": format_won(b.paid),
            "부담액": format_won(b.owed),
            "차액": _signed_won(b.net),
        }
        for b in balances
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    caption = "차액이 +이면 받을 돈, -이면 보낼 돈입니다."
    if trip.mode == "fund":
        caption += (
            f" 회비형에서 낸 돈에는 1인 회비 {format_won(trip.fund_per_person)}이 포함됩니다."
        )
    st.caption(caption)


def _is_leader_wallet(transfer: Transfer, trip: Trip) -> bool:
    """회비형에서 대표와 회비 지갑 사이 송금. 대표가 지갑을 들고 있어 자기 자신에게 보내는 꼴이다."""
    return trip.mode == "fund" and {transfer.sender, transfer.receiver} == {
        trip.leader,
        FUND_WALLET,
    }


def _render_transfers(transfers: list[Transfer], trip: Trip) -> None:
    st.subheader("송금 메시지")
    if not transfers:
        st.success("주고받을 돈이 없습니다.")
        return
    for transfer in transfers:
        amount = format_won(transfer.amount)
        if _is_leader_wallet(transfer, trip) and transfer.sender == trip.leader:
            st.info(
                f"대표가 직접 채울 금액: {amount} (대표 {trip.leader}님이 회비 지갑에 보탭니다)"
            )
        elif _is_leader_wallet(transfer, trip):
            st.info(f"대표 몫 환급: 대표 {trip.leader}님이 회비 지갑에서 {amount}을 가져갑니다")
        else:
            st.code(build_message(transfer, trip), language=None)
