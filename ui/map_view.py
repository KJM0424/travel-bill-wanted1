"""정산 결과 아래 여행 경로 지도: 결제 순서대로 번호 마커와 움직이는 선."""

import folium
import streamlit as st
from folium.plugins import AntPath
from streamlit_folium import st_folium

from core.config import get_setting
from core.expense_builder import sort_expenses
from core.geocode import Coords, GeoResult, geocode_trip, is_mappable
from core.schema import Expense, Trip
from ui.state import session

# .streamlit/config.toml의 primaryColor와 같은 값이다.
ROUTE_COLOR = "#17654C"
MAP_HEIGHT = 450
GEO_CACHE_KEY = "geo_cache"
NO_KEY_INFO = (
    "카카오 키가 없어서 지도를 보여 줄 수 없어요. KAKAO_REST_API_KEY를 넣으면 경로가 보여요."
)
LOAD_ERROR = "위치를 불러오지 못했어요. 잠시 뒤에 다시 열어 주세요."
MARKER_HTML = (
    '<div style="width:26px;height:26px;border-radius:50%;background:{color};color:#fff;'
    "border:2px solid #fff;font:700 13px/22px Pretendard,sans-serif;text-align:center;"
    'box-shadow:0 0 0 1px {color};">{number}</div>'
)


def kakao_api_key() -> str:
    return (get_setting("KAKAO_REST_API_KEY") or "").strip()


def build_route_map(points: list[tuple[str, float, float]]) -> folium.Map:
    """(이름, lat, lng)를 시간순으로 받아 번호 마커와 AntPath 경로를 그린다."""
    m = folium.Map(location=[points[0][1], points[0][2]], zoom_start=12, tiles="OpenStreetMap")
    for number, (name, lat, lng) in enumerate(points, start=1):
        folium.Marker(
            [lat, lng],
            tooltip=f"{number}. {name}",
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


def _cache_query(expense: Expense) -> list[str]:
    # 상호명·주소가 바뀌면 좌표도 다시 찾는다. 세션 상태에 넣으므로 tuple 대신 list로 둔다.
    return [expense.merchant_name, expense.merchant_address or ""]


def locate(expenses: list[Expense], api_key: str) -> dict[str, GeoResult]:
    """찾은 좌표만 세션에 캐시한다. 못 찾았거나 조회가 실패한 건은 다음 화면에서 다시 찾는다."""
    cache: dict = session().setdefault(GEO_CACHE_KEY, {})
    known: dict[str, Coords] = {}
    for e in expenses:
        hit = cache.get(e.expense_id)
        if hit and hit["query"] == _cache_query(e):
            known[e.expense_id] = tuple(hit["coords"])
    results = geocode_trip(expenses, api_key, known=known)
    for e in expenses:
        result = results.get(e.expense_id)
        if result and result.coords:
            cache[e.expense_id] = {"query": _cache_query(e), "coords": list(result.coords)}
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
    found = [(e, results[e.expense_id].coords) for e in expenses if results[e.expense_id].coords]
    failed = [e for e in expenses if results[e.expense_id].failed]
    if not found and failed:
        # 키 오류·한도 초과·네트워크 문제. 주소가 틀려서 못 찾은 것과 구분한다.
        st.warning(LOAD_ERROR)
        return
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
    not_found = [e for e in expenses if not results[e.expense_id].coords and e not in failed]
    if not_found:
        st.caption(f"위치를 찾지 못한 결제: {_names(not_found)}")
    if failed:
        st.caption(f"위치를 불러오지 못한 결제: {_names(failed)}")


def _names(expenses: list[Expense]) -> str:
    return ", ".join(e.merchant_name for e in expenses)
