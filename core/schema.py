"""모든 모듈이 공유하는 데이터 계약: AI 인식 결과, 결제 건, 여행."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FUND_WALLET = "회비 지갑"

DocType = Literal["receipt", "booking_capture", "card_slip", "not_receipt"]
Category = Literal["food", "cafe", "lodging", "transport", "shopping", "activity", "etc"]


class LineItem(BaseModel):
    name: str
    amount: int


class Receipt(BaseModel):
    """AI 인식 결과. Gemini response_schema로도 쓴다.

    기본값을 두지 않아 Gemini가 모든 필드를 채우게 한다.

    카드번호·승인번호·전화번호 필드는 의도적으로 두지 않는다.
    """

    doc_type: DocType
    merchant_name: str | None
    merchant_address: str | None
    paid_at: str | None = Field(description='"YYYY-MM-DDTHH:MM", 시간이 없으면 "YYYY-MM-DD"')
    total_amount: int | None = Field(description="할인·포인트를 반영한 실제 결제 금액")
    currency: str = Field(description='통화 코드, 한국 원화는 "KRW"')
    category: Category
    items: list[LineItem]
    warnings: list[str]


class Expense(BaseModel):
    """정산 단위가 되는 결제 건. 사용자가 화면에서 수정한다."""

    expense_id: str
    source: Literal["ai", "manual"]
    merchant_name: str
    merchant_address: str | None = None
    paid_at: datetime | None = None
    time_known: bool = False
    amount: int = Field(ge=0)
    category: Category = "etc"
    payer: str
    participants: list[str]
    excluded: bool = False
    image_hash: str | None = None
    warnings: list[str] = []


class PayoutInfo(BaseModel):
    bank_account: str | None = None
    toss_link: str | None = None
    kakaopay_link: str | None = None


class Trip(BaseModel):
    name: str
    members: list[str]
    leader: str
    mode: Literal["prepaid", "fund"]
    fund_per_person: int = 0
    start_date: date
    end_date: date
    payout: dict[str, PayoutInfo] = {}
    expenses: list[Expense] = []

    @field_validator("members")
    @classmethod
    def _check_members(cls, members: list[str]) -> list[str]:
        names = [m.strip() for m in members]
        if not names:
            raise ValueError("참석자를 1명 이상 입력하세요.")
        if any(not n for n in names):
            raise ValueError("빈 참석자 이름이 있습니다.")
        if FUND_WALLET in names:
            raise ValueError(f"'{FUND_WALLET}'은 참석자 이름으로 쓸 수 없습니다.")
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"참석자 이름이 중복됩니다: {', '.join(duplicates)}")
        return names

    @field_validator("leader")
    @classmethod
    def _strip_leader(cls, leader: str) -> str:
        return leader.strip()

    @model_validator(mode="after")
    def _check_trip(self) -> "Trip":
        if self.leader not in self.members:
            raise ValueError(f"대표 '{self.leader}'가 참석자 목록에 없습니다.")
        if self.end_date < self.start_date:
            raise ValueError("여행 종료일이 시작일보다 빠릅니다.")
        if self.mode == "fund" and self.fund_per_person <= 0:
            raise ValueError("회비형은 1인 회비를 0원보다 크게 입력하세요.")
        return self


def parse_paid_at(value: str | None) -> tuple[datetime | None, bool]:
    """인식된 일시 문자열을 (값, 시간을 아는지)로 바꾼다. 해석할 수 없으면 (None, False)."""
    if not value:
        return None, False
    for fmt, time_known in (("%Y-%m-%dT%H:%M", True), ("%Y-%m-%d", False)):
        try:
            return datetime.strptime(value.strip(), fmt), time_known
        except ValueError:
            continue
    return None, False
