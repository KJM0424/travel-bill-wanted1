"""송금 한 건마다 복사해서 보낼 메시지를 만든다."""

from core.schema import FUND_WALLET, PayoutInfo, Trip
from core.settlement import Transfer

NO_PAYOUT_NOTICE = "받는 분께 계좌를 확인해 주세요."


def format_won(amount: int) -> str:
    return f"{amount:,}원"


def _payout_lines(payout: PayoutInfo | None) -> list[str]:
    """정보가 있는 송금 수단만 한 줄씩. 하나도 없으면 안내 문구 한 줄."""
    if payout is None:
        return [NO_PAYOUT_NOTICE]
    channels = [
        ("계좌", payout.bank_account),
        ("토스", payout.toss_link),
        ("카카오페이", payout.kakaopay_link),
    ]
    lines = [f"{label}: {value}" for label, value in channels if value]
    return lines or [NO_PAYOUT_NOTICE]


def build_message(transfer: Transfer, trip: Trip) -> str:
    amount = format_won(transfer.amount)
    receiver = transfer.receiver
    if transfer.sender == FUND_WALLET:
        first = f"[{trip.name}] 대표 {trip.leader}님이 {receiver}님께 회비 {amount}을 환급해요."
    elif receiver == FUND_WALLET:
        first = f"[{trip.name}] {transfer.sender}님 → {FUND_WALLET}(대표 {trip.leader}) {amount}"
    else:
        first = f"[{trip.name}] {transfer.sender}님 → {receiver}님 {amount}"

    # 회비 지갑으로 보내는 돈은 대표가 받는다.
    payout_owner = trip.leader if receiver == FUND_WALLET else receiver
    return "\n".join([first, *_payout_lines(trip.payout.get(payout_owner))])
