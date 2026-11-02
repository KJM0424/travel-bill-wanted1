"""여행 돌아보기: 날짜별 묶음, 이동 거리, 요약 숫자. 화면과 무관한 계산만 한다."""

import math
from dataclasses import dataclass
from datetime import date
from itertools import groupby, pairwise

from core.expense_builder import sort_expenses
from core.schema import Category, Expense, Trip

Coords = tuple[float, float]
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class TripStats:
    length_label: str
    count: int
    total: int
    busiest_day: tuple[date, int] | None
    biggest: tuple[str, int] | None
    # (분류, 퍼센트). 큰 순서이고 합은 100이다.
    shares: list[tuple[Category, int]]


def haversine_km(a: Coords, b: Coords) -> float:
    """두 좌표 사이 직선(대권) 거리."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def route_km(points: list[Coords]) -> float:
    """들른 순서대로 이은 직선거리의 합. 실제 도로 거리보다 짧다."""
    return sum(haversine_km(a, b) for a, b in pairwise(points))


def trip_length_label(start: date, end: date) -> str:
    days = (end - start).days + 1
    return "당일치기" if days <= 1 else f"{days - 1}박 {days}일"


def group_days(expenses: list[Expense]) -> list[tuple[date | None, list[Expense]]]:
    """결제를 날짜별로 묶는다. 날짜순이고, 날짜를 모르는 결제는 맨 뒤 None 묶음이다."""
    ordered = sort_expenses(expenses)
    return [
        (day, list(group))
        for day, group in groupby(ordered, key=lambda e: e.paid_at.date() if e.paid_at else None)
    ]


def summarize_trip(trip: Trip) -> TripStats:
    active = [e for e in trip.expenses if not e.excluded]
    day_totals = [
        (day, sum(e.amount for e in group)) for day, group in group_days(active) if day is not None
    ]
    busiest = max(day_totals, key=lambda d: d[1], default=None)
    biggest = max(active, key=lambda e: e.amount, default=None)
    return TripStats(
        length_label=trip_length_label(trip.start_date, trip.end_date),
        count=len(active),
        total=sum(e.amount for e in active),
        busiest_day=busiest,
        biggest=(biggest.merchant_name, biggest.amount) if biggest else None,
        shares=_category_shares(active),
    )


def _category_shares(expenses: list[Expense]) -> list[tuple[Category, int]]:
    totals: dict[Category, int] = {}
    for e in expenses:
        totals[e.category] = totals.get(e.category, 0) + e.amount
    grand = sum(totals.values())
    if grand <= 0:
        return []
    # 반올림하면 합이 99나 101이 될 수 있어, 내림한 뒤 나머지가 큰 순서로 1씩 더한다.
    exact = {c: amount * 100 / grand for c, amount in totals.items()}
    shares = {c: math.floor(v) for c, v in exact.items()}
    for c in sorted(exact, key=lambda c: exact[c] - shares[c], reverse=True)[
        : 100 - sum(shares.values())
    ]:
        shares[c] += 1
    ranked = sorted(shares.items(), key=lambda s: (-totals[s[0]], s[0]))
    return [(c, p) for c, p in ranked if p > 0]
