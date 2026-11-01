"""UI 테스트가 함께 쓰는 여행·결제 건 생성기와 AppTest 헬퍼."""

from datetime import date, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.schema import Expense, Trip

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


def exp(
    amount: int,
    payer: str,
    participants: list[str],
    id: str = "e1",
    merchant: str = "가게",
    paid_at: datetime | None = None,
    time_known: bool = False,
) -> Expense:
    return Expense(
        expense_id=id,
        source="manual",
        merchant_name=merchant,
        paid_at=paid_at,
        time_known=time_known,
        amount=amount,
        payer=payer,
        participants=participants,
    )


def trip_with(
    expenses: list[Expense], mode: str = "prepaid", fee: int = 0, members: list[str] | None = None
) -> Trip:
    return Trip(
        name="제주",
        members=members or ["A", "B", "C"],
        leader="A",
        mode=mode,
        fund_per_person=fee,
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 12),
        expenses=expenses,
    )


def open_app(monkeypatch) -> AppTest:
    monkeypatch.setenv("RECOGNIZER", "mock")
    monkeypatch.setenv("APP_PASSWORD", "")
    return AppTest.from_file(APP_PATH, default_timeout=30).run()


def open_app_with_trip(
    monkeypatch, expenses: list[Expense], step: str = "검토", **trip_kwargs
) -> AppTest:
    monkeypatch.setenv("RECOGNIZER", "mock")
    monkeypatch.setenv("APP_PASSWORD", "")
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.session_state["trip"] = trip_with(expenses, **trip_kwargs)
    at.session_state["step"] = step
    return at.run()


def fill_setup(at: AppTest, members: str, mode: str = "선결제형", fee: int = 0) -> AppTest:
    at.text_input(key="setup_name").input("제주").run()
    at.text_input(key="setup_members").input(members).run()
    at.segmented_control(key="setup_mode").set_value(mode).run()
    if mode == "회비형":
        at.number_input(key="setup_fee").set_value(fee).run()
    return at
