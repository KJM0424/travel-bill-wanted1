from datetime import date, datetime

import pytest

from core.schema import Expense, Trip
from core.trip_story import (
    curve_points,
    group_days,
    haversine_km,
    route_km,
    summarize_trip,
    trip_length_label,
)


def spend(
    id: str,
    amount: int,
    paid_at: datetime | None,
    category: str = "food",
    merchant: str | None = None,
    excluded: bool = False,
) -> Expense:
    return Expense(
        expense_id=id,
        source="ai",
        merchant_name=merchant or id,
        paid_at=paid_at,
        time_known=paid_at is not None,
        amount=amount,
        category=category,
        payer="A",
        participants=["A", "B"],
        excluded=excluded,
    )


def make_trip(expenses: list[Expense], start: date = date(2026, 10, 10), end=None) -> Trip:
    return Trip(
        name="제주",
        members=["A", "B"],
        leader="A",
        mode="prepaid",
        start_date=start,
        end_date=end or date(2026, 10, 12),
        expenses=expenses,
    )


def test_haversine_seoul_to_busan_is_about_325km():
    assert haversine_km((37.5665, 126.9780), (35.1796, 129.0756)) == pytest.approx(325, abs=3)


def test_haversine_same_point_is_zero():
    assert haversine_km((33.5, 126.5), (33.5, 126.5)) == 0


def test_route_km_adds_legs_in_order():
    a, b, c = (33.0, 126.0), (33.1, 126.0), (33.1, 126.1)
    assert route_km([a, b, c]) == pytest.approx(haversine_km(a, b) + haversine_km(b, c))
    assert route_km([a]) == 0 and route_km([]) == 0


@pytest.mark.parametrize(
    ("start", "end", "label"),
    [
        (date(2026, 10, 10), date(2026, 10, 12), "2박 3일"),
        (date(2026, 10, 10), date(2026, 10, 11), "1박 2일"),
        (date(2026, 10, 10), date(2026, 10, 10), "당일치기"),
    ],
)
def test_trip_length_label(start, end, label):
    assert trip_length_label(start, end) == label


def test_group_days_orders_by_date_with_unknown_last():
    e1 = spend("e1", 1000, datetime(2026, 10, 11, 9))
    e2 = spend("e2", 1000, datetime(2026, 10, 10, 20))
    e3 = spend("e3", 1000, None)
    e4 = spend("e4", 1000, datetime(2026, 10, 10, 8))
    days = group_days([e1, e2, e3, e4])
    assert [d for d, _ in days] == [date(2026, 10, 10), date(2026, 10, 11), None]
    assert [e.expense_id for e in days[0][1]] == ["e4", "e2"]


def test_summarize_ignores_excluded_expenses():
    trip = make_trip(
        [
            spend("국수", 30000, datetime(2026, 10, 10, 12)),
            spend("빠진건", 900000, datetime(2026, 10, 10, 13), excluded=True),
        ]
    )
    stats = summarize_trip(trip)
    assert stats.count == 1 and stats.total == 30000
    assert stats.biggest == ("국수", 30000)


def test_summarize_busiest_day_and_biggest_payment():
    trip = make_trip(
        [
            spend("국수", 30000, datetime(2026, 10, 10, 12)),
            spend("카페", 12000, datetime(2026, 10, 10, 15), category="cafe"),
            spend("호텔", 180000, datetime(2026, 10, 11, 15), category="lodging"),
            spend("생선구이", 96000, datetime(2026, 10, 11, 19)),
            spend("날짜모름", 500000, None, category="etc"),
        ]
    )
    stats = summarize_trip(trip)
    assert stats.busiest_day == (date(2026, 10, 11), 276000)
    assert stats.biggest == ("날짜모름", 500000)
    assert stats.length_label == "2박 3일"


def test_summarize_category_shares_largest_first_and_sum_to_100():
    trip = make_trip(
        [
            spend("국수", 30000, datetime(2026, 10, 10, 12)),
            spend("카페", 10000, datetime(2026, 10, 10, 15), category="cafe"),
            spend("호텔", 60000, datetime(2026, 10, 11, 15), category="lodging"),
        ]
    )
    shares = summarize_trip(trip).shares
    assert shares == [("lodging", 60), ("food", 30), ("cafe", 10)]


def test_summarize_rounding_still_sums_to_100():
    trip = make_trip(
        [
            spend("a", 1, datetime(2026, 10, 10, 12)),
            spend("b", 1, datetime(2026, 10, 10, 13), category="cafe"),
            spend("c", 1, datetime(2026, 10, 10, 14), category="shopping"),
        ]
    )
    assert sum(p for _, p in summarize_trip(trip).shares) == 100


def test_summarize_empty_trip_has_no_highlights():
    stats = summarize_trip(make_trip([]))
    assert stats.count == 0 and stats.total == 0
    assert stats.busiest_day is None and stats.biggest is None and stats.shares == []


def test_curve_starts_and_ends_at_the_two_points():
    a, b = (33.46, 126.31), (33.25, 126.41)
    points = curve_points(a, b, steps=20)
    assert len(points) == 21
    assert points[0] == a and points[-1] == b


def test_curve_bends_away_from_the_straight_line():
    a, b = (33.0, 126.0), (33.0, 127.0)
    middle = curve_points(a, b, steps=20)[10]
    straight_middle = (33.0, 126.5)
    assert haversine_km(middle, straight_middle) > 5
    assert middle[1] == pytest.approx(126.5, abs=0.01)


def test_curve_back_and_forth_does_not_overlap():
    a, b = (33.0, 126.0), (33.0, 127.0)
    there = curve_points(a, b, steps=20)[10]
    back = curve_points(b, a, steps=20)[10]
    assert haversine_km(there, back) > 10


def test_curve_between_same_point_is_just_that_point():
    assert curve_points((33.5, 126.5), (33.5, 126.5)) == [(33.5, 126.5), (33.5, 126.5)]
