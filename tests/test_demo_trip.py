from pathlib import Path

from eval.make_demo_trip import DEMO_TRIP_PATH, build_demo_trip
from ui.result_step import import_trip


def test_committed_demo_trip_matches_specs():
    # 영수증 설정(eval/synthetic_specs.json)을 바꾸면 시연 파일도 다시 만들어야 한다.
    assert Path(DEMO_TRIP_PATH).read_text(encoding="utf-8") == build_demo_trip().model_dump_json(
        indent=2
    )


def test_demo_trip_loads_like_a_saved_file():
    trip = import_trip(Path(DEMO_TRIP_PATH).read_bytes())
    assert len(trip.expenses) == 13 and trip.leader == "재민"


def test_demo_trip_shows_several_payers_and_a_skipped_friend():
    trip = build_demo_trip()
    assert {e.payer for e in trip.expenses} == {"재민", "수아", "민호"}
    cafe = next(e for e in trip.expenses if e.merchant_name == "인디고인디드")
    assert cafe.participants == ["재민", "수아"]


def test_demo_trip_amounts_match_ground_truth():
    trip = build_demo_trip()
    by_name = {e.merchant_name: e.amount for e in trip.expenses}
    assert by_name["중문생선구이 중문본점"] == 96000
    assert trip.payout["재민"].bank == "카카오뱅크"
