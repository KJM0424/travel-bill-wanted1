import requests

from core.geocode import geocode
from core.schema import Expense


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """URL 끝부분(address.json, keyword.json)별로 정해 둔 응답을 돌려준다."""

    def __init__(self, responses: dict[str, dict], status_code: int = 200):
        self._responses = responses
        self._status_code = status_code
        self.calls: list[dict] = []
        self.last_headers: dict = {}

    def get(self, url: str, params=None, headers=None, timeout=None) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        self.last_headers = headers or {}
        for suffix, payload in self._responses.items():
            if url.endswith(suffix):
                return FakeResponse(self._status_code, payload)
        return FakeResponse(self._status_code, {"documents": []})


class RaisingSession(FakeSession):
    def get(self, url: str, params=None, headers=None, timeout=None) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        raise requests.ConnectionError("network down")


def fake_session(responses: dict[str, dict]) -> FakeSession:
    return FakeSession(responses)


def failing_session(status_code: int) -> FakeSession:
    return FakeSession({}, status_code=status_code)


def mk(address: str | None = None, merchant: str = "가게") -> Expense:
    return Expense(
        expense_id="e1",
        source="ai",
        merchant_name=merchant,
        merchant_address=address,
        amount=1000,
        payer="A",
        participants=["A"],
    )


def test_uses_address_search_first():
    s = fake_session({"address.json": {"documents": [{"x": "126.3", "y": "33.4"}]}})
    assert geocode(mk(address="제주 제주시 애월읍 1"), "k", s) == (33.4, 126.3)
    assert len(s.calls) == 1
    assert s.calls[0]["params"] == {"query": "제주 제주시 애월읍 1"}


def test_falls_back_to_keyword_search():
    s = fake_session(
        {
            "address.json": {"documents": []},
            "keyword.json": {"documents": [{"x": "126.5", "y": "33.5"}]},
        }
    )
    assert geocode(mk(address="이상한 주소", merchant="스타벅스 애월점"), "k", s) == (33.5, 126.5)
    assert s.calls[1]["params"] == {"query": "스타벅스 애월점"}


def test_returns_none_on_http_error_or_no_result():
    no_result = fake_session({"keyword.json": {"documents": []}})
    assert geocode(mk(address=None, merchant="없는가게"), "k", no_result) is None
    assert geocode(mk(address="x"), "k", failing_session(500)) is None
    assert geocode(mk(address="x"), "k", failing_session(401)) is None


def test_returns_none_on_network_error():
    assert geocode(mk(address="x"), "k", RaisingSession({})) is None


def test_skips_address_search_when_address_missing():
    s = fake_session({"keyword.json": {"documents": [{"x": "126.5", "y": "33.5"}]}})
    assert geocode(mk(address=None, merchant="카페"), "k", s) == (33.5, 126.5)
    assert [c["url"].rsplit("/", 1)[-1] for c in s.calls] == ["keyword.json"]


def test_skips_keyword_search_when_merchant_blank():
    s = fake_session({"address.json": {"documents": []}})
    assert geocode(mk(address="x", merchant="  "), "k", s) is None
    assert len(s.calls) == 1


def test_returns_none_on_malformed_coordinates():
    s = fake_session({"address.json": {"documents": [{"x": "", "y": "abc"}]}})
    assert geocode(mk(address="x", merchant=" "), "k", s) is None


def test_sends_kakao_auth_header():
    s = fake_session({"address.json": {"documents": [{"x": "1", "y": "2"}]}})
    geocode(mk(address="x"), "abc", s)
    assert s.last_headers["Authorization"] == "KakaoAK abc"


def test_sets_request_timeout():
    s = fake_session({"address.json": {"documents": [{"x": "1", "y": "2"}]}})
    geocode(mk(address="x"), "k", s)
    assert s.calls[0]["timeout"] == 5


def test_returns_none_without_request_when_api_key_missing():
    s = fake_session({"address.json": {"documents": [{"x": "1", "y": "2"}]}})
    assert geocode(mk(address="x"), "", s) is None
    assert s.calls == []
