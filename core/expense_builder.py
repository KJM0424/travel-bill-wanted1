"""인식 결과를 결제 건으로 바꾸고, 정렬하고, 중복을 찾는다."""

from datetime import date, datetime, timedelta

from core.recognize_service import RecognitionOutcome
from core.schema import FUND_WALLET, Expense, Receipt, Trip, parse_paid_at

DUPLICATE_WINDOW = timedelta(minutes=10)
UNKNOWN_MERCHANT = "상호 미상"


def build_expenses(
    outcomes: list[RecognitionOutcome], trip: Trip
) -> tuple[list[Expense], list[str]]:
    """(결제 건, 사용자 안내 메시지)를 돌려준다. 영수증이 아니거나 원화가 아니면 제외한다."""
    expenses: list[Expense] = []
    notes: list[str] = []
    used_ids: set[str] = set()
    for outcome in outcomes:
        receipt = outcome.receipt
        if receipt is None:
            notes.append(f"{outcome.filename}: 인식 실패({outcome.error}). 수동으로 추가하세요.")
            continue
        if receipt.doc_type == "not_receipt":
            notes.append(f"{outcome.filename}: 영수증이 아니어서 제외했습니다.")
            continue
        if receipt.currency != "KRW":
            notes.append(
                f"{outcome.filename}: 원화(KRW)가 아닌 결제({receipt.currency})라서 제외했습니다."
            )
            continue
        expense_id = _unique_id(outcome.image_hash[:12], used_ids)
        expenses.append(_to_expense(receipt, expense_id, outcome.image_hash, trip))
    return expenses, notes


def _unique_id(base: str, used: set[str]) -> str:
    candidate, n = base, 1
    while candidate in used:
        n += 1
        candidate = f"{base}-{n}"
    used.add(candidate)
    return candidate


def _to_expense(receipt: Receipt, expense_id: str, digest: str, trip: Trip) -> Expense:
    warnings = list(receipt.warnings)
    if receipt.total_amount is None:
        warnings.append("금액을 인식하지 못했습니다. 직접 입력하세요.")
    if not receipt.merchant_name:
        warnings.append("상호를 인식하지 못했습니다.")
    paid_at, time_known = parse_paid_at(receipt.paid_at)
    if receipt.paid_at and paid_at is None:
        warnings.append(f"결제 일시를 해석하지 못했습니다: {receipt.paid_at}")
    if paid_at is not None:
        paid_at, date_warnings = _check_trip_dates(paid_at, trip)
        warnings.extend(date_warnings)
    return Expense(
        expense_id=expense_id,
        source="ai",
        merchant_name=receipt.merchant_name or UNKNOWN_MERCHANT,
        merchant_address=receipt.merchant_address,
        paid_at=paid_at,
        time_known=time_known,
        amount=max(receipt.total_amount or 0, 0),
        category=receipt.category,
        payer=FUND_WALLET if trip.mode == "fund" else trip.leader,
        participants=list(trip.members),
        image_hash=digest,
        warnings=warnings,
    )


def _check_trip_dates(paid_at: datetime, trip: Trip) -> tuple[datetime, list[str]]:
    """연도만 바꿔서 여행 기간에 들어오면 고친다. 그래도 밖이면 경고만 남긴다."""
    if _in_trip(paid_at.date(), trip):
        return paid_at, []
    try:
        corrected = paid_at.replace(year=trip.start_date.year)
    except ValueError:  # 2월 29일
        corrected = None
    if corrected and paid_at.year != corrected.year and _in_trip(corrected.date(), trip):
        return corrected, [f"연도를 {paid_at.year}년에서 {corrected.year}년으로 고쳤습니다."]
    return paid_at, ["결제 날짜가 여행 기간 밖입니다."]


def _in_trip(day: date, trip: Trip) -> bool:
    return trip.start_date <= day <= trip.end_date


def sort_expenses(expenses: list[Expense]) -> list[Expense]:
    """날짜순. 같은 날에는 날짜만 아는 건이 먼저, 일시를 모르는 건은 맨 뒤."""

    def key(e: Expense) -> tuple:
        if e.paid_at is None:
            return (True,)
        return (False, e.paid_at.date(), e.time_known, e.paid_at.time())

    return sorted(expenses, key=key)


def find_duplicates(expenses: list[Expense]) -> list[tuple[str, str]]:
    """금액이 같고 시각 차이가 10분 이내인 쌍. 시간을 아는 건끼리만 비교한다."""
    timed = sorted(
        (e for e in expenses if e.time_known and e.paid_at is not None), key=lambda e: e.paid_at
    )
    pairs = []
    for i, first in enumerate(timed):
        for second in timed[i + 1 :]:
            if second.paid_at - first.paid_at > DUPLICATE_WINDOW:
                break
            if first.amount == second.amount:
                pairs.append((first.expense_id, second.expense_id))
    return pairs
