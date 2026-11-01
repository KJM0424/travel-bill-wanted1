"""결제 건의 주소·상호명을 좌표(lat, lng)로 바꾼다."""

import requests

from core.kakao_client import KakaoLocalClient
from core.schema import Expense


def geocode(
    expense: Expense, api_key: str, session: requests.Session | None = None
) -> tuple[float, float] | None:
    """주소 검색을 먼저 하고, 결과가 없으면 상호명 키워드 검색을 한다. 못 찾으면 None."""
    if not api_key:
        return None
    client = KakaoLocalClient(api_key, session)
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
