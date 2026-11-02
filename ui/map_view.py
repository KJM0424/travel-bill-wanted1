"""정산 결과 아래 '여행 돌아보기': 요약 카드, 날짜별 색 경로 지도, 다시 보기, 날짜별 동선."""

import html
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise

import folium
import streamlit as st
from branca.element import MacroElement, Template
from folium.plugins import AntPath
from streamlit_folium import st_folium

from core.config import get_setting
from core.expense_builder import sort_expenses
from core.geocode import GeoResult, geocode_trip, is_mappable
from core.payment_message import format_won
from core.schema import Category, Expense, Trip
from core.trip_story import TripStats, curve_points, group_days, route_km, summarize_trip
from ui.state import session

# 1일차는 .streamlit/config.toml의 primaryColor(여권 초록)다. 지도 바탕(OSM) 위에서 서로 구분되는 색만 골랐다.
DAY_COLORS = ["#17654C", "#3166D6", "#E0662B", "#8350D4", "#D2386C", "#0E7C86"]
UNKNOWN_DAY_COLOR = "#8B95A1"
# 날짜가 바뀌는 구간은 회색 점선으로 잇는다.
DAY_JUMP_STYLE = {"color": "#8B95A1", "weight": 3, "dash_array": "6 8", "opacity": 0.9}
MAP_HEIGHT = 450
ALL_DAYS = "전체"
DAY_KEY = "map_day"
REPLAY_LABEL = "여행 다시 보기"
# 다시 보기에서 한 구간을 달리는 시간과 장소에 도착한 뒤 쉬는 시간
REPLAY_LEG_MS = 1100
REPLAY_PAUSE_MS = 250
# folium이 기본으로 불러오는 Font Awesome 6 아이콘 이름이다.
CATEGORY_ICONS: dict[Category, str] = {
    "food": "fa-utensils",
    "cafe": "fa-mug-hot",
    "lodging": "fa-bed",
    "transport": "fa-car",
    "shopping": "fa-bag-shopping",
    "activity": "fa-ticket",
    "etc": "fa-receipt",
}
CATEGORY_NAMES: dict[Category, str] = {
    "food": "식비",
    "cafe": "카페",
    "lodging": "숙소",
    "transport": "교통",
    "shopping": "쇼핑",
    "activity": "놀거리",
    "etc": "기타",
}
# 분류 비율 막대는 큰 순서로 여권 초록을 옅게 칠한다. 지도의 날짜 색과 겹치면 같은 색이 두 뜻이 된다.
SHARE_COLORS = ["#17654C", "#3F8A6F", "#6DAA92", "#9CC8B6", "#C7E1D6", "#DDE9E4", "#EEF5F1"]
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
    '<div style="width:30px;height:30px;border-radius:50%;background:{color};color:#fff;'
    "border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);display:flex;"
    'align-items:center;justify-content:center;font-size:13px;">'
    '<i class="fa-solid {icon}"></i></div>'
)
POPUP_HTML = (
    '<div style="font:14px/1.5 Pretendard,sans-serif;color:#191F28;min-width:150px">'
    '<b style="font-size:15px">{name}</b><br>'
    '<span style="color:#6B7684">{when}</span><br>'
    "<b>{amount}</b><br>"
    '<span style="color:#6B7684">함께: {people}</span></div>'
)


@dataclass(frozen=True)
class Stop:
    """지도에 찍을 결제 한 건. day는 날짜 색 번호(0부터)이고, -1이면 날짜를 모른다."""

    name: str
    lat: float
    lng: float
    day: int
    category: Category
    when: str
    amount: int
    people: str


class _Replay(MacroElement):
    """'여행 다시 보기' 버튼. 누르면 경로를 지우고, 자동차가 결제 순서대로 곡선을 따라 달리며 선을 다시 그린다.

    folium 기본 플러그인(TimestampedGeoJson)은 실제 시간 단위로 움직여 빈 시간대가 길고
    외부 스크립트를 여러 개 더 불러와서, Leaflet만으로 직접 만든다.
    구간마다 거리와 관계없이 같은 시간(LEG_MS)을 쓰고, 출발·도착에서 천천히 움직이게 한다.
    """

    _template = Template("""
{% macro script(this, kwargs) %}
(function () {
  var map = {{ this._parent.get_name() }};
  var route = {{ this.route.get_name() }};
  var markers = [{{ this.marker_names }}];
  var legs = {{ this.legs }};
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var legMs = reduce ? 0 : {{ this.leg_ms }};
  var pauseMs = reduce ? 0 : {{ this.pause_ms }};
  var timer = null, frame = null, layer = null;
  var carIcon = L.divIcon({
    html: '<div class="tv-car" style="width:34px;height:34px;border-radius:50%;background:#fff;' +
      'color:#17654C;display:flex;align-items:center;justify-content:center;font-size:17px;' +
      'box-shadow:0 2px 6px rgba(0,0,0,.35);"><i class="fa-solid fa-car-side"></i></div>',
    className: "", iconSize: [34, 34], iconAnchor: [17, 17]
  });
  function reset() {
    clearTimeout(timer);
    cancelAnimationFrame(frame);
    if (layer) { map.removeLayer(layer); layer = null; }
    if (!map.hasLayer(route)) { map.addLayer(route); }
  }
  function ease(p) { return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2; }
  function play() {
    reset();
    map.removeLayer(route);
    layer = L.layerGroup().addTo(map);
    markers[0].addTo(layer);
    var car = L.marker(legs[0].points[0], { icon: carIcon, interactive: false, zIndexOffset: 1000 });
    car.addTo(layer);
    var leg = 0;
    function drive() {
      if (leg >= legs.length) { timer = setTimeout(reset, 1500); return; }
      var pts = legs[leg].points;
      var line = L.polyline([pts[0]], legs[leg].style).addTo(layer);
      var start = null;
      function step(t) {
        if (start === null) { start = t; }
        var p = legMs ? Math.min(1, (t - start) / legMs) : 1;
        var at = ease(p) * (pts.length - 1), i = Math.floor(at), f = at - i;
        var a = pts[i], b = pts[Math.min(i + 1, pts.length - 1)];
        var pos = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
        line.setLatLngs(pts.slice(0, i + 1).concat([pos]));
        car.setLatLng(pos);
        var body = car.getElement() && car.getElement().querySelector(".tv-car i");
        // 아이콘은 오른쪽을 본다. 서쪽으로 갈 때만 뒤집는다.
        if (body && b[1] !== a[1]) { body.style.transform = b[1] < a[1] ? "scaleX(-1)" : ""; }
        if (p < 1) { frame = requestAnimationFrame(step); return; }
        leg += 1;
        markers[leg].addTo(layer);
        timer = setTimeout(drive, pauseMs);
      }
      frame = requestAnimationFrame(step);
    }
    timer = setTimeout(drive, pauseMs);
  }
  var Button = L.Control.extend({
    options: { position: "topright" },
    onAdd: function () {
      var b = L.DomUtil.create("button");
      b.type = "button";
      b.textContent = "\u25b6 {{ this.label }}";
      b.style.cssText = "background:#17654C;color:#fff;border:0;border-radius:999px;" +
        "padding:8px 14px;font:600 14px Pretendard,sans-serif;cursor:pointer;" +
        "box-shadow:0 1px 4px rgba(0,0,0,.3);min-height:36px";
      L.DomEvent.disableClickPropagation(b);
      L.DomEvent.on(b, "click", play);
      return b;
    }
  });
  new Button().addTo(map);
})();
{% endmacro %}
""")

    def __init__(self, route: folium.FeatureGroup, markers: list[folium.Marker], stops: list[Stop]):
        super().__init__()
        self._name = "Replay"
        self.route = route
        self.marker_names = ", ".join(m.get_name() for m in markers)
        legs = [
            {"points": _leg_points(a, b), "style": _leg_style(a, b)} for a, b in pairwise(stops)
        ]
        self.legs = json.dumps(legs)
        self.leg_ms = REPLAY_LEG_MS
        self.pause_ms = REPLAY_PAUSE_MS
        self.label = REPLAY_LABEL


now = time.monotonic


def kakao_api_key() -> str:
    return (get_setting("KAKAO_REST_API_KEY") or "").strip()


def _safe_text(text: str) -> str:
    """folium은 툴팁 글을 JS 템플릿 문자열(`...`)에 그대로 넣는다. HTML과 `·$를 모두 막는다."""
    return html.escape(text).replace("`", "&#96;").replace("$", "&#36;")


def day_color(day: int) -> str:
    return UNKNOWN_DAY_COLOR if day < 0 else DAY_COLORS[day % len(DAY_COLORS)]


def _leg_style(a: Stop, b: Stop) -> dict:
    # Leaflet 옵션 이름 그대로다(다시 보기 스크립트가 L.polyline에 넘긴다).
    if a.day != b.day:
        return {"color": DAY_JUMP_STYLE["color"], "weight": 3, "dashArray": "6 8"}
    return {"color": day_color(b.day), "weight": 4}


def _leg_points(a: Stop, b: Stop) -> list[list[float]]:
    return [[lat, lng] for lat, lng in curve_points((a.lat, a.lng), (b.lat, b.lng))]


def build_route_map(stops: list[Stop]) -> folium.Map:
    """시간순 결제를 날짜별 색 곡선으로 잇는다. 같은 날은 움직이는 선, 날짜가 바뀌면 회색 점선."""
    m = folium.Map(location=[stops[0].lat, stops[0].lng], zoom_start=13, tiles="OpenStreetMap")
    route = folium.FeatureGroup(name="route", control=False).add_to(m)
    markers = [_marker(s).add_to(route) for s in stops]
    # 같은 날 이어진 구간은 하나의 선으로 모아 그린다. 날짜가 바뀌면 지금까지 모은 선을 끝낸다.
    run: list[list[float]] = []
    for a, b in pairwise(stops):
        points = _leg_points(a, b)
        if a.day != b.day:
            _add_day_path(route, run, a.day)
            run = []
            folium.PolyLine(points, **DAY_JUMP_STYLE).add_to(route)
        else:
            run = run + points[1:] if run else points
    _add_day_path(route, run, stops[-1].day)
    if len(stops) > 1:
        m.fit_bounds([[s.lat, s.lng] for s in stops], padding=(30, 30))
        _Replay(route, markers, stops).add_to(m)
    return m


def _add_day_path(route: folium.FeatureGroup, points: list[list[float]], day: int) -> None:
    if len(points) > 1:
        AntPath(points, color=day_color(day), pulse_color="#FFFFFF", weight=4, delay=1200).add_to(
            route
        )


def _marker(stop: Stop) -> folium.Marker:
    popup = POPUP_HTML.format(
        name=_safe_text(stop.name),
        when=_safe_text(stop.when or "시간 모름"),
        amount=format_won(stop.amount),
        people=_safe_text(stop.people),
    )
    return folium.Marker(
        [stop.lat, stop.lng],
        tooltip=_safe_text(stop.name),
        popup=folium.Popup(popup, max_width=240),
        icon=folium.DivIcon(
            html=MARKER_HTML.format(color=day_color(stop.day), icon=CATEGORY_ICONS[stop.category]),
            icon_size=(30, 30),
            icon_anchor=(15, 15),
        ),
    )


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
    active = [e for e in trip.expenses if not e.excluded]
    if not active:
        return
    # 위치 조회가 끝나야 이동 거리를 알 수 있다. 자리를 먼저 잡고 나중에 채운다.
    card = st.container()
    days = group_days(active)
    tags = {day: day_tag(day, trip) for day, _ in days}
    places = [e for e in sort_expenses(active) if is_mappable(e)]
    results = _locate_places(places)
    found = [(e, results[e.expense_id].coords) for e in places if e.expense_id in results]
    found = [(e, c) for e, c in found if c]
    km = route_km([c for _, c in found]) if len(found) > 1 else None
    card.html(story_html(summarize_trip(trip), km))

    place_days = [day for day, group in days if any(is_mappable(e) for e in group)]
    picked = _pick_day([tags[d] for d in place_days])
    shown_days = [d for d in place_days if picked in (ALL_DAYS, tags[d])]
    stops = [
        _stop(e, c, day_index(_day_of(e), trip), trip) for e, c in found if _day_of(e) in shown_days
    ]
    if stops:
        st_folium(
            build_route_map(stops),
            height=MAP_HEIGHT,
            use_container_width=True,
            returned_objects=[],
            key=f"route_map_{picked}",
        )
    for day, group in days:
        if day in shown_days:
            _render_day_line(tags[day], day_index(day, trip), group)
    if results:
        _caption_unresolved(places, results)


def day_index(day: date | None, trip: Trip) -> int:
    """날짜 색 번호. 1일차가 0이고, 여행 기간 밖이거나 날짜를 모르면 -1(회색)이다."""
    if day is None or not trip.start_date <= day <= trip.end_date:
        return -1
    return (day - trip.start_date).days


def day_tag(day: date | None, trip: Trip) -> str:
    """여행 기간 안이면 'n일차', 밖이면(미리 결제한 숙소 등) 날짜, 모르면 '날짜 모름'."""
    if day is None:
        return "날짜 모름"
    if trip.start_date <= day <= trip.end_date:
        return f"{(day - trip.start_date).days + 1}일차"
    return f"{day.month}월 {day.day}일"


def story_html(stats: TripStats, km: float | None) -> str:
    """여행 요약 카드. 상호명은 AI가 읽었거나 사용자가 고친 값이라 이스케이프한다."""
    if stats.length_label == "당일치기":
        head = f"당일치기 여행에서 {stats.count}번 결제했어요"
    else:
        head = f"{stats.length_label} 동안 {stats.count}번 결제했어요"
    rows = []
    if km is not None:
        distance = f"{km:.1f}" if km < 10 else f"{km:,.0f}"
        rows.append(("이동 거리", f"약 {distance}km", "들른 곳 사이 직선거리"))
    if stats.busiest_day:
        day, amount = stats.busiest_day
        rows.append(("가장 많이 쓴 날", format_won(amount), f"{day.month}월 {day.day}일"))
    if stats.biggest:
        name, amount = stats.biggest
        rows.append(("가장 큰 결제", format_won(amount), name))
    items = "".join(
        f"<dt>{label}</dt><dd>{value}<small>{html.escape(note)}</small></dd>"
        for label, value, note in rows
    )
    shades = [SHARE_COLORS[min(i, len(SHARE_COLORS) - 1)] for i in range(len(stats.shares))]
    bar = "".join(
        f'<span style="width:{pct}%;background:{shade}"></span>'
        for (_, pct), shade in zip(stats.shares, shades, strict=True)
    )
    legend = "".join(
        f'<li><i style="background:{shade}"></i>{CATEGORY_NAMES[c]} {pct}%</li>'
        for (c, pct), shade in zip(stats.shares, shades, strict=True)
    )
    return (
        f'<div class="tv-story"><p class="tv-story-head">{head}</p><dl>{items}</dl>'
        f'<div class="tv-bar" aria-hidden="true">{bar}</div><ul class="tv-legend">{legend}</ul></div>'
    )


def _locate_places(places: list[Expense]) -> dict[str, GeoResult]:
    """키가 없거나 모두 실패하면 안내만 하고 빈 결과를 돌려준다."""
    if not places:
        return {}
    api_key = kakao_api_key()
    if not api_key:
        st.info(NO_KEY_INFO)
        return {}
    with st.spinner("결제한 곳을 지도에 찍고 있어요"):
        results = locate(places, api_key)
    if all(results[e.expense_id].failed for e in places):
        # 키 오류·한도 초과·네트워크 문제. 주소가 틀려서 못 찾은 것과 구분한다.
        st.warning(LOAD_ERROR)
        return {}
    return results


def _pick_day(tags: list[str]) -> str:
    if len(tags) < 2:
        return ALL_DAYS
    options = [ALL_DAYS, *tags]
    # 결제를 고쳐 그 날짜가 사라졌으면 고른 값을 버린다. 없는 값을 넘기면 위젯이 오류를 낸다.
    if session().get(DAY_KEY) not in (None, *options):
        del session()[DAY_KEY]
    picked = st.pills("날짜", options, default=ALL_DAYS, key=DAY_KEY, label_visibility="collapsed")
    return picked or ALL_DAYS


def _render_day_line(tag: str, color_index: int, group: list[Expense]) -> None:
    names = " → ".join(html.escape(e.merchant_name) for e in group if is_mappable(e))
    total = format_won(sum(e.amount for e in group))
    dot = f'<span style="color:{day_color(color_index)}">●</span>'
    st.markdown(
        f"{dot} **{tag}** &nbsp;{total}  \n{names}",
        unsafe_allow_html=True,
    )


def _caption_unresolved(places: list[Expense], results: dict[str, GeoResult]) -> None:
    failed = [e for e in places if results[e.expense_id].failed]
    not_found = [
        e for e in places if not results[e.expense_id].coords and not results[e.expense_id].failed
    ]
    if not_found:
        st.caption(f"위치를 찾지 못한 결제: {_names(not_found)}")
    if failed:
        st.caption(f"위치를 불러오지 못한 결제: {_names(failed)}")


def _day_of(expense: Expense) -> date | None:
    return expense.paid_at.date() if expense.paid_at else None


def _stop(expense: Expense, coords: tuple[float, float], day: int, trip: Trip) -> Stop:
    everyone = sorted(expense.participants) == sorted(trip.members)
    return Stop(
        name=expense.merchant_name,
        lat=coords[0],
        lng=coords[1],
        day=day,
        category=expense.category,
        when=_when(expense.paid_at, expense.time_known),
        amount=expense.amount,
        people="모두" if everyone else ", ".join(expense.participants),
    )


def _when(paid_at: datetime | None, time_known: bool) -> str:
    if paid_at is None:
        return ""
    text = f"{paid_at.month}월 {paid_at.day}일"
    return f"{text} {paid_at:%H:%M}" if time_known else text


def _names(expenses: list[Expense]) -> str:
    return ", ".join(e.merchant_name for e in expenses)
