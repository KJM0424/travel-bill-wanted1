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


def curve_points(a: Coords, b: Coords, bend: float = 0.18, steps: int = 24) -> list[Coords]:
    """a에서 b로 가는 완만한 곡선(2차 베지어)의 점들. 양 끝은 a, b 그대로다.

    가는 방향의 오른쪽으로 휜다. 그래서 갔다가 돌아오는 길은 서로 겹치지 않는다.
    위도 1도와 경도 1도의 길이가 달라서, 경도에 cos(위도)를 곱한 평면에서 계산한다.
    """
    if a == b:
        return [a, b]
    scale = math.cos(math.radians((a[0] + b[0]) / 2))
    ax, ay, bx, by = a[1] * scale, a[0], b[1] * scale, b[0]
    dx, dy = bx - ax, by - ay
    # 진행 방향 (dx, dy)의 오른쪽 수직 방향은 (dy, -dx)다.
    cx, cy = (ax + bx) / 2 + dy * bend, (ay + by) / 2 - dx * bend
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * ax + 2 * (1 - t) * t * cx + t**2 * bx
        y = (1 - t) ** 2 * ay + 2 * (1 - t) * t * cy + t**2 * by
        points.append((y, x / scale))
    points[0], points[-1] = a, b
    return points


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
