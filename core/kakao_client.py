"""카카오 로컬 API 호출. 실패는 예외 대신 None으로 돌려준다."""

import requests

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TIMEOUT_SECONDS = 5


class KakaoLocalClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        self._headers = {"Authorization": f"KakaoAK {api_key}"}
        self._session = session or requests.Session()

    def search_address(self, query: str) -> list[dict] | None:
        return self._search(ADDRESS_URL, query)

    def search_keyword(self, query: str) -> list[dict] | None:
        return self._search(KEYWORD_URL, query)

    def _search(self, url: str, query: str) -> list[dict] | None:
        """검색 결과 documents를 돌려준다. 네트워크 오류·4xx/5xx·응답 형식 오류는 None."""
        try:
            response = self._session.get(
                url, params={"query": query}, headers=self._headers, timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            documents = response.json().get("documents")
        except (requests.RequestException, ValueError, AttributeError):
            return None
        return documents if isinstance(documents, list) else None
