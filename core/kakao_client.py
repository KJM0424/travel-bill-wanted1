"""카카오 로컬 API 호출. 실패는 예외 대신 None으로 돌려준다."""

import requests

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TIMEOUT_SECONDS = 5
# 카카오 키워드 검색 반경의 최댓값(미터).
MAX_RADIUS_METERS = 20000


class KakaoLocalClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self._headers = {"Authorization": f"KakaoAK {api_key.strip()}"}
        self._session = session or requests.Session()

    def search_address(self, query: str) -> list[dict] | None:
        return self._search(ADDRESS_URL, {"query": query})

    def search_keyword(
        self, query: str, near: tuple[float, float] | None = None
    ) -> list[dict] | None:
        """near(lat, lng)가 있으면 그 지점 반경 20km 안에서만 찾는다."""
        params: dict = {"query": query}
        if near is not None:
            lat, lng = near
            params.update({"x": str(lng), "y": str(lat), "radius": MAX_RADIUS_METERS})
        return self._search(KEYWORD_URL, params)

    def _search(self, url: str, params: dict) -> list[dict] | None:
        """검색 결과 documents를 돌려준다. 네트워크 오류·4xx/5xx·응답 형식 오류는 None."""
        try:
            response = self._session.get(
                url, params=params, headers=self._headers, timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            documents = response.json().get("documents")
        except (requests.RequestException, ValueError, AttributeError):
            return None
        return documents if isinstance(documents, list) else None
