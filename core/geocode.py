"""결제 건의 주소·상호명을 좌표(lat, lng)로 바꾼다."""

import requests

from core.kakao_client import KakaoLocalClient
from core.schema import Expense


def geocode(
    expense: Expense, api_key: str, session: requests.Session | None = None
) -> tuple[float, float] | None:
    """주소 검색을 먼저 하고, 결과가 없으면 상호명 키워드 검색을 한다. 못 찾으면 None.

    여러 건을 변환할 때는 session 하나를 만들어 넘기면 연결을 재사용한다.
    session을 넘기지 않으면 이 호출 안에서 만들고 닫는다.
    """
    if not api_key:
        return None
    if session is None:
        own_session = requests.Session()
        try:
            return _geocode_with(KakaoLocalClient(api_key, own_session), expense)
        finally:
            own_session.close()
    return _geocode_with(KakaoLocalClient(api_key, session), expense)


def _geocode_with(client: KakaoLocalClient, expense: Expense) -> tuple[float, float] | None:
    address = (expense.merchant_address or "").strip()
    if address:
        coords = _first_coords(client.search_address(address))
        if coords:
            return coords
    merchant = expense.merchant_name.strip()
    if merchant:
        return _first_coords(client.search_keyword(merchant))
    return None


def _first_coords(documents: list[dict] | None) -> tuple[float, float] | None:
    # 카카오 응답은 x가 경도(lng), y가 위도(lat)다.
    if not documents:
        return None
    try:
        return float(documents[0]["y"]), float(documents[0]["x"])
    except (KeyError, TypeError, ValueError):
        return None
