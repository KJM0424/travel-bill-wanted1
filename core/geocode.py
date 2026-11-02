"""결제 건의 주소·상호명을 좌표(lat, lng)로 바꾼다."""

import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import requests

from core.kakao_client import KakaoLocalClient
from core.schema import Expense

Coords = tuple[float, float]


@dataclass(frozen=True)
class GeoResult:
    """coords가 None이면 위치를 모른다. failed는 '못 찾음'이 아니라 조회 자체가 실패했다는 뜻이다."""

    coords: Coords | None
    failed: bool = False


def is_mappable(expense: Expense) -> bool:
    """지도에 올릴 결제인가. 교통비는 한 장소가 아니고, 직접 추가한 건은 주소가 없다."""
    return not expense.excluded and expense.category != "transport" and expense.source != "manual"


def geocode(
    expense: Expense, api_key: str, session: requests.Session | None = None
) -> Coords | None:
    """주소 검색을 먼저 하고, 결과가 없으면 상호명 키워드 검색을 한다. 못 찾으면 None.

    여러 건을 변환할 때는 geocode_trip을 쓴다.
    session을 넘기지 않으면 이 호출 안에서 만들고 닫는다.
    """
    api_key = api_key.strip()
    if not api_key:
        return None
    with _session_scope(session) as s:
        client = KakaoLocalClient(api_key, s)
        address = _search_address(client, expense)
        if address.coords:
            return address.coords
        return _search_keyword(client, expense, near=None).coords


def geocode_trip(
    expenses: list[Expense], api_key: str, session: requests.Session | None = None
) -> dict[str, GeoResult]:
    """지도에 올릴 결제만 expense_id별로 변환한다. expenses는 시간순으로 넘긴다.

    주소로 찾은 결제가 있으면, 주소가 없거나 못 찾은 결제의 상호명 검색은
    시간순으로 가장 가까운 '주소로 찾은 지점' 근처로 제한한다.
    흔한 상호명(예: 스타벅스)이 엉뚱한 지역을 찍는 일을 줄인다.
    모든 요청은 session 하나로 보낸다.
    """
    api_key = api_key.strip()
    targets = [e for e in expenses if is_mappable(e)]
    if not api_key or not targets:
        return {}
    with _session_scope(session) as s:
        client = KakaoLocalClient(api_key, s)
        by_address = [_search_address(client, e) for e in targets]
        anchors = [(i, r.coords) for i, r in enumerate(by_address) if r.coords]
        results: dict[str, GeoResult] = {}
        for i, (expense, address) in enumerate(zip(targets, by_address, strict=True)):
            if address.coords:
                results[expense.expense_id] = address
                continue
            keyword = _search_keyword(client, expense, near=_nearest_anchor(i, anchors))
            failed = keyword.coords is None and (address.failed or keyword.failed)
            results[expense.expense_id] = GeoResult(keyword.coords, failed)
        return results


@contextmanager
def _session_scope(session: requests.Session | None) -> Iterator[requests.Session]:
    """넘겨받은 session은 그대로 쓰고, 없으면 만들어서 다 쓰고 닫는다."""
    if session is not None:
        yield session
        return
    own = requests.Session()
    try:
        yield own
    finally:
        own.close()


def _nearest_anchor(index: int, anchors: list[tuple[int, Coords]]) -> Coords | None:
    if not anchors:
        return None
    return min(anchors, key=lambda a: abs(a[0] - index))[1]


def _search_address(client: KakaoLocalClient, expense: Expense) -> GeoResult:
    address = (expense.merchant_address or "").strip()
    if not address:
        return GeoResult(None)
    return _to_result(client.search_address(address))


def _search_keyword(client: KakaoLocalClient, expense: Expense, near: Coords | None) -> GeoResult:
    merchant = expense.merchant_name.strip()
    if not merchant:
        return GeoResult(None)
    return _to_result(client.search_keyword(merchant, near=near))


def _to_result(documents: list[dict] | None) -> GeoResult:
    # 클라이언트는 요청 실패를 None, 결과 없음을 빈 목록으로 돌려준다.
    if documents is None:
        return GeoResult(None, failed=True)
    return GeoResult(_first_coords(documents))


def _first_coords(documents: list[dict]) -> Coords | None:
    # 카카오 응답은 x가 경도(lng), y가 위도(lat)다.
    if not documents:
        return None
    try:
        lat, lng = float(documents[0]["y"]), float(documents[0]["x"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng
