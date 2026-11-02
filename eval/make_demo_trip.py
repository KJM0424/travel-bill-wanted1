"""시연용 정산 파일(eval/demo_trip.json)을 만든다. 시작 화면의 '저장한 정산 이어서 하기'로 불러온다.

영수증 13장(eval/synthetic_specs.json)을 AI가 정확히 읽었다고 보고, 결제자·함께한 사람을 정해 둔다.
AI 호출 없이 검토·정산·여행 돌아보기를 바로 보여 줄 수 있다. 가게와 거래는 지어낸 것이다.
"""

import json
from datetime import date, datetime
from pathlib import Path

from core.schema import Category, Expense, PayoutInfo, Trip

EVAL_DIR = Path(__file__).parent
SPECS_PATH = EVAL_DIR / "synthetic_specs.json"
GROUND_TRUTH_PATH = EVAL_DIR / "ground_truth.json"
DEMO_TRIP_PATH = EVAL_DIR / "demo_trip.json"

MEMBERS = ["재민", "수아", "민호"]
CATEGORIES: dict[str, Category] = {
    "food": "food",
    "cafe": "cafe",
    "lodging": "lodging",
    "transport": "transport",
    "mart": "shopping",
}
# 결제자가 여러 명인 여행: 숙소·차는 총무, 먹고 마신 건 돌아가며 냈다.
PAYERS = {
    "s01": "재민",
    "s02": "재민",
    "s03": "재민",
    "s04": "수아",
    "s05": "민호",
    "s06": "수아",
    "s07": "민호",
    "s08": "수아",
    "s09": "민호",
    "s10": "수아",
    "s11": "민호",
    "s12": "재민",
    "s13": "재민",
}
# 민호는 첫날 카페에 가지 않았다. 검토 화면에서 '빠진 사람' 예시로 보여 준다.
SKIPPED = {"s08": ["민호"]}


def build_demo_trip() -> Trip:
    specs = json.loads(SPECS_PATH.read_text(encoding="utf-8"))
    amounts = {
        Path(g["file"]).stem: g["expected"]["total_amount"]
        for g in json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
        if g["source"] == "synthetic"
    }
    expenses = [_expense(spec, amounts[spec["id"]]) for spec in specs]
    return Trip(
        name="제주 2박 3일",
        members=MEMBERS,
        leader="재민",
        mode="prepaid",
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 12),
        payout={
            "재민": PayoutInfo(
                bank="카카오뱅크", account_number="3333-01-1234567", account_holder="김재민"
            )
        },
        expenses=sorted(expenses, key=_order),
    )


def _expense(spec: dict, amount: int) -> Expense:
    time_known = "T" in spec["paid_at"]
    paid_at = datetime.fromisoformat(spec["paid_at"])
    warnings = []
    if not date(2026, 10, 10) <= paid_at.date() <= date(2026, 10, 12):
        warnings.append("결제 날짜가 여행 기간 밖이에요.")
    skipped = SKIPPED.get(spec["id"], [])
    return Expense(
        expense_id=spec["id"],
        source="ai",
        merchant_name=spec["merchant"],
        merchant_address=spec["address"],
        paid_at=paid_at,
        time_known=time_known,
        amount=amount,
        category=CATEGORIES[spec["kind"]],
        payer=PAYERS[spec["id"]],
        participants=[m for m in MEMBERS if m not in skipped],
        warnings=warnings,
    )


def _order(e: Expense) -> tuple:
    # 앱과 같은 순서: 날짜순, 같은 날에는 날짜만 아는 건이 먼저(core/expense_builder.sort_expenses).
    return (e.paid_at.date(), e.time_known, e.paid_at.time())


def main() -> None:
    DEMO_TRIP_PATH.write_text(build_demo_trip().model_dump_json(indent=2), encoding="utf-8")
    print(f"시연 파일: {DEMO_TRIP_PATH}")


if __name__ == "__main__":
    main()
