"""송금 한 건마다 복사해서 보낼 메시지를 만든다."""

import re

from core.schema import FUND_WALLET, PayoutInfo, Trip
from core.settlement import Transfer

NO_PAYOUT_NOTICE = "받는 분께 계좌를 확인해 주세요."
# 국내 은행 계좌번호는 숫자 10~14자리가 대부분이다. 증권사·옛 계좌까지 넉넉히 받는다.
ACCOUNT_DIGITS = (8, 16)
ACCOUNT_NUMBER_ERROR = "계좌번호는 숫자와 -로 8~16자리를 적어 주세요."
# 설정 화면의 은행 고르기 목록. 목록에 없는 은행은 직접 적을 수 있다.
BANKS = [
    "KB국민은행",
    "신한은행",
    "우리은행",
    "하나은행",
    "NH농협은행",
    "IBK기업은행",
    "카카오뱅크",
    "토스뱅크",
    "케이뱅크",
    "SC제일은행",
    "우체국",
    "새마을금고",
    "신협",
    "수협은행",
    "iM뱅크",
    "부산은행",
    "경남은행",
    "광주은행",
    "전북은행",
    "제주은행",
    "KDB산업은행",
    "씨티은행",
]
_OLD_ACCOUNT = re.compile(r"^\s*(\S+)\s+([\d-]{8,})\s*(.*?)\s*$")


def format_won(amount: int) -> str:
    return f"{amount:,}원"


def clean_account_number(text: str) -> str:
    """띄어쓰기를 지운 계좌번호. 숫자와 - 말고 다른 글자가 있거나 자릿수가 맞지 않으면 ValueError."""
    number = re.sub(r"\s+", "", text)
    digits = number.replace("-", "")
    low, high = ACCOUNT_DIGITS
    if not digits.isdigit() or not low <= len(digits) <= high:
        raise ValueError(ACCOUNT_NUMBER_ERROR)
    return number


def split_old_account(text: str) -> tuple[str, str, str | None] | None:
    """예전 한 칸 형식 '은행 계좌번호 예금주'를 나눈다. 모양이 다르면 None."""
    match = _OLD_ACCOUNT.match(text)
    if not match:
        return None
    bank, number, holder = match.groups()
    return bank, number, holder or None


def match_bank(name: str) -> str:
    """'신한', '국민'처럼 줄여 쓴 이름을 목록의 이름으로 바꾼다. 못 찾으면 적은 그대로 둔다."""
    name = name.strip()
    if name in BANKS:
        return name
    return next((bank for bank in BANKS if name and name in bank), name)


def account_copy_text(payout: PayoutInfo | None) -> str | None:
    """은행 앱에 붙여 넣을 '은행 계좌번호'. 예금주는 넣지 않는다."""
    if payout is None:
        return None
    if payout.bank and payout.account_number:
        return f"{payout.bank} {payout.account_number}"
    return payout.bank_account


def _account_line(payout: PayoutInfo) -> str | None:
    text = account_copy_text(payout)
    if text and payout.account_holder and not payout.bank_account:
        return f"{text} (예금주 {payout.account_holder})"
    return text


def payout_owner(transfer: Transfer, trip: Trip) -> str:
    """돈을 실제로 받는 사람. 회비 지갑으로 보내는 돈은 총무가 받는다."""
    return trip.leader if transfer.receiver == FUND_WALLET else transfer.receiver


def _payout_lines(payout: PayoutInfo | None) -> list[str]:
    """정보가 있는 송금 수단만 한 줄씩. 하나도 없으면 안내 문구 한 줄."""
    if payout is None:
        return [NO_PAYOUT_NOTICE]
    channels = [
        ("계좌", _account_line(payout)),
        ("토스", payout.toss_link),
        ("카카오페이", payout.kakaopay_link),
    ]
    lines = [f"{label}: {value}" for label, value in channels if value]
    return lines or [NO_PAYOUT_NOTICE]


def build_message(transfer: Transfer, trip: Trip) -> str:
    amount = format_won(transfer.amount)
    receiver = transfer.receiver
    if transfer.sender == FUND_WALLET:
        first = (
            f"[{trip.name}] 총무 {trip.leader}님이 {receiver}님께 남은 회비 {amount}을 돌려드려요."
        )
    elif receiver == FUND_WALLET:
        first = f"[{trip.name}] {transfer.sender}님 → {FUND_WALLET}(총무 {trip.leader}) {amount}"
    else:
        first = f"[{trip.name}] {transfer.sender}님 → {receiver}님 {amount}"

    return "\n".join([first, *_payout_lines(trip.payout.get(payout_owner(transfer, trip)))])
