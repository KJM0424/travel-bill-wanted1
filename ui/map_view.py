"""정산 결과 아래 여행 경로 지도: 결제 순서대로 번호 마커와 움직이는 선."""

import html
import time

import folium
import streamlit as st
from folium.plugins import AntPath
from streamlit_folium import st_folium

from core.config import get_setting
from core.expense_builder import sort_expenses
from core.geocode import GeoResult, geocode_trip, is_mappable
from core.schema import Expense, Trip
from ui.state import session

# .streamlit/config.toml의 primaryColor와 같은 값이다.
ROUTE_COLOR = "#17654C"
MAP_HEIGHT = 450
GEO_CACHE_KEY = "geo_cache"
# 화면은 버튼을 누를 때마다 다시 그려진다. 못 찾은 결과를 세션 내내 붙잡지도,
# 다시 그릴 때마다 카카오를 다시 부르지도 않도록 정해 둔 시간 동안만 재사용한다.
RETRY_FAILED_SECONDS = 30
RETRY_NOT_FOUND_SECONDS = 600
NO_KEY_INFO = (
    "카카오 키가 없어서 지도를 보여 줄 수 없어요. KAKAO_REST_API_KEY를 넣으면 경로가 보여요."
)
LOAD_ERROR = "위치를 불러오지 못했어요. 잠시 뒤에 다시 열어 주세요."
MARKER_HTML = (
    '<div style="width:26px;height:26px;border-radius:50%;background:{color};color:#fff;'
    "border:2px solid #fff;font:700 13px/22px Pretendard,sans-serif;text-align:center;"
    'box-shadow:0 0 0 1px {color};">{number}</div>'
)

now = time.monotonic


def kakao_api_key() -> str:
    return (get_setting("KAKAO_REST_API_KEY") or "").strip()


def _safe_text(text: str) -> str:
    """folium은 툴팁 글을 JS 템플릿 문자열(`...`)에 그대로 넣는다. HTML과 `·$를 모두 막는다."""
    return html.escape(text).replace("`", "&#96;").replace("$", "&#36;")


def build_route_map(points: list[tuple[str, float, float]]) -> folium.Map:
    """(이름, lat, lng)를 시간순으로 받아 번호 마커와 AntPath 경로를 그린다."""
    m = folium.Map(location=[points[0][1], points[0][2]], zoom_start=12, tiles="OpenStreetMap")
    for number, (name, lat, lng) in enumerate(points, start=1):
        folium.Marker(
            [lat, lng],
            tooltip=_safe_text(f"{number}. {name}"),
            icon=folium.DivIcon(
                html=MARKER_HTML.format(color=ROUTE_COLOR, number=number),
                icon_size=(26, 26),
                icon_anchor=(13, 13),
            ),
        ).add_to(m)
    if len(points) > 1:
        locations = [[lat, lng] for _, lat, lng in points]
        AntPath(locations, color=ROUTE_COLOR, pulse_color="#FFFFFF", weight=4, delay=1200).add_to(m)
        m.fit_bounds(locations, padding=(30, 30))
    return m


def _places(expenses: list[Expense]) -> list[list[str]]:
    # 순서·상호명·주소가 하나라도 바뀌면 기준 지점이 달라질 수 있어 전부 다시 찾는다.
    return [[e.expense_id, e.merchant_name, e.merchant_address or ""] for e in expenses]


def _expires_at(results: dict[str, GeoResult]) -> float | None:
    if any(r.failed for r in results.values()):
        return now() + RETRY_FAILED_SECONDS
    if any(r.coords is None for r in results.values()):
        return now() + RETRY_NOT_FOUND_SECONDS
    return None


def locate(expenses: list[Expense], api_key: str) -> dict[str, GeoResult]:
    """결제 장소 목록이 같고 만료 전이면 지난 결과를 그대로 쓴다."""
    places = _places(expenses)
    cached = session().get(GEO_CACHE_KEY)
    if cached and cached["places"] == places:
        expires_at = cached["expires_at"]
        if expires_at is None or now() < expires_at:
            return cached["results"]
    results = geocode_trip(expenses, api_key)
    session()[GEO_CACHE_KEY] = {
        "places": places,
        "results": results,
        "expires_at": _expires_at(results),
    }
    return results


def render_map(trip: Trip) -> None:
    expenses = [e for e in sort_expenses(trip.expenses) if is_mappable(e)]
    if not expenses:
        return
    st.subheader("여행 경로", anchor=False)
    api_key = kakao_api_key()
    if not api_key:
        st.info(NO_KEY_INFO)
        return
    with st.spinner("결제한 곳을 지도에 찍고 있어요"):
        results = locate(expenses, api_key)
    failed = [e for e in expenses if results[e.expense_id].failed]
    if len(failed) == len(expenses):
        # 키 오류·한도 초과·네트워크 문제. 주소가 틀려서 못 찾은 것과 구분한다.
        st.warning(LOAD_ERROR)
        return
    found = [(e, results[e.expense_id].coords) for e in expenses if results[e.expense_id].coords]
    if found:
        st.caption("결제한 순서대로 번호를 붙였어요.")
        points = [(e.merchant_name, lat, lng) for e, (lat, lng) in found]
        st_folium(
            build_route_map(points),
            height=MAP_HEIGHT,
            use_container_width=True,
            returned_objects=[],
            key="route_map",
        )
    not_found = [
        e for e in expenses if not results[e.expense_id].coords and not results[e.expense_id].failed
    ]
    if not_found:
        st.caption(f"위치를 찾지 못한 결제: {_names(not_found)}")
    if failed:
        st.caption(f"위치를 불러오지 못한 결제: {_names(failed)}")


def _names(expenses: list[Expense]) -> str:
    return ", ".join(e.merchant_name for e in expenses)
