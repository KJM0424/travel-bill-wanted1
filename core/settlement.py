"""정산 계산: 사람별 낸 돈·부담액과 송금 경로. 순수 함수만 둔다."""

from dataclasses import dataclass

from core.schema import FUND_WALLET, Trip


@dataclass(frozen=True)
class Balance:
    name: str
    paid: int
    owed: int
    net: int  # paid - owed. 양수면 받을 돈, 음수면 보낼 돈


@dataclass(frozen=True)
class Transfer:
    sender: str
    receiver: str
    amount: int


def _account_names(trip: Trip) -> list[str]:
    """정산 대상 이름. members 순서이고, 회비형이면 회비 지갑이 마지막이다."""
    return [*trip.members, FUND_WALLET] if trip.mode == "fund" else list(trip.members)


def readiness_errors(trip: Trip) -> list[str]:
    """정산 단계로 넘어가지 못하게 막는 이유 목록. 비어 있으면 정산할 수 있다."""
    active = [e for e in trip.expenses if not e.excluded]
    if not active:
        return ["결제 건이 없습니다."]

    valid_payers = set(_account_names(trip))
    errors = []
    for expense in active:
        name = expense.merchant_name
        if expense.amount <= 0:
            errors.append(f"'{name}' 금액이 0원입니다.")
        if not expense.participants:
            errors.append(f"'{name}' 참석자가 없습니다.")
        # 결제자가 그 건의 참석자가 아닌 것은 허용한다(결제만 하고 먹지 않은 경우).
        if expense.payer not in valid_payers:
            errors.append(f"'{name}' 결제자가 여행 참석자가 아닙니다.")
    return errors


def compute_balances(trip: Trip) -> list[Balance]:
    """사람별 낸 돈과 부담액. 1원 단위 나머지는 결제자가 부담한다."""
    names = _account_names(trip)
    paid = dict.fromkeys(names, 0)
    owed = dict.fromkeys(names, 0)

    for expense in trip.expenses:
        if expense.excluded:
            continue
        count = len(expense.participants)
        share = expense.amount // count
        for person in expense.participants:
            owed[person] += share
        owed[expense.payer] += expense.amount - share * count
        paid[expense.payer] += expense.amount

    if trip.mode == "fund":
        for member in trip.members:
            paid[member] += trip.fund_per_person
        owed[FUND_WALLET] += trip.fund_per_person * len(trip.members)

    return [Balance(n, paid[n], owed[n], paid[n] - owed[n]) for n in names]


def plan_transfers(balances: list[Balance]) -> list[Transfer]:
    """보낼 사람과 받을 사람을 금액이 큰 순서로 짝지어 송금 횟수를 줄인다."""
    debtors = sorted(([b.name, -b.net] for b in balances if b.net < 0), key=lambda x: (-x[1], x[0]))
    creditors = sorted(
        ([b.name, b.net] for b in balances if b.net > 0), key=lambda x: (-x[1], x[0])
    )
    transfers = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1])
        transfers.append(Transfer(debtors[i][0], creditors[j][0], amount))
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        i += debtors[i][1] == 0
        j += creditors[j][1] == 0
    return transfers
