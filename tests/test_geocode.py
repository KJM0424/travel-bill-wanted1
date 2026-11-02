import pytest
import requests

from core.geocode import GeoResult, geocode, geocode_trip, is_mappable
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


def test_closes_session_it_created(monkeypatch):
    created: list[FakeSession] = []

    class ClosableSession(FakeSession):
        closed = False

        def close(self) -> None:
            self.closed = True

    def make_session() -> ClosableSession:
        s = ClosableSession({"address.json": {"documents": [{"x": "1", "y": "2"}]}})
        created.append(s)
        return s

    monkeypatch.setattr(requests, "Session", make_session)
    assert geocode(mk(address="x"), "k") == (2.0, 1.0)
    assert len(created) == 1 and created[0].closed


# --- 여행 단위 변환 (Task 18) ---


class QuerySession(FakeSession):
    """검색어별로 정해 둔 documents를 돌려준다. 정하지 않은 검색어는 결과 없음."""

    def __init__(self, documents_by_query: dict[str, list[dict]], status_code: int = 200):
        super().__init__({}, status_code)
        self._documents = documents_by_query

    def get(self, url: str, params=None, headers=None, timeout=None) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        self.last_headers = headers or {}
        documents = self._documents.get(params["query"], [])
        return FakeResponse(self._status_code, {"documents": documents})


def trip_exp(
    id: str,
    address: str | None = None,
    merchant: str = "가게",
    category: str = "food",
    source: str = "ai",
    excluded: bool = False,
) -> Expense:
    return Expense(
        expense_id=id,
        source=source,
        merchant_name=merchant,
        merchant_address=address,
        amount=1000,
        category=category,
        payer="A",
        participants=["A"],
        excluded=excluded,
    )


def keyword_calls(s: FakeSession) -> list[dict]:
    return [c["params"] for c in s.calls if c["url"].endswith("keyword.json")]


def test_trip_keyword_search_limited_near_address_found_point():
    s = QuerySession({"제주 애월 1": [{"x": "126.3", "y": "33.4"}], "스타벅스": []})
    geocode_trip(
        [trip_exp("e1", address="제주 애월 1"), trip_exp("e2", merchant="스타벅스")], "k", s
    )
    assert keyword_calls(s) == [{"query": "스타벅스", "x": "126.3", "y": "33.4", "radius": 20000}]


def test_trip_keyword_search_unlimited_without_address_found_point():
    s = QuerySession({})
    geocode_trip([trip_exp("e1", merchant="스타벅스")], "k", s)
    assert keyword_calls(s) == [{"query": "스타벅스"}]


def test_trip_keyword_search_uses_nearest_found_point_in_order():
    s = QuerySession(
        {
            "제주 주소": [{"x": "126.3", "y": "33.4"}],
            "서울 주소": [{"x": "127.0", "y": "37.5"}],
        }
    )
    expenses = [
        trip_exp("e1", address="제주 주소"),
        trip_exp("e2", merchant="제주 카페"),
        trip_exp("e3", merchant="서울 카페"),
        trip_exp("e4", address="서울 주소"),
    ]
    geocode_trip(expenses, "k", s)
    near = {c["query"]: (c.get("x"), c.get("y")) for c in keyword_calls(s)}
    assert near == {"제주 카페": ("126.3", "33.4"), "서울 카페": ("127.0", "37.5")}


def test_trip_returns_found_and_not_found():
    s = QuerySession({"제주 애월 1": [{"x": "126.3", "y": "33.4"}]})
    results = geocode_trip(
        [trip_exp("e1", address="제주 애월 1"), trip_exp("e2", merchant="없는가게")], "k", s
    )
    assert results == {
        "e1": GeoResult(coords=(33.4, 126.3)),
        "e2": GeoResult(coords=None, failed=False),
    }


def test_trip_marks_lookup_failure_separately_from_not_found():
    results = geocode_trip([trip_exp("e1", address="x")], "k", QuerySession({}, status_code=401))
    assert results == {"e1": GeoResult(coords=None, failed=True)}
    results = geocode_trip([trip_exp("e1", address="x")], "k", RaisingSession({}))
    assert results["e1"].failed


def test_trip_skips_transport_manual_and_excluded():
    s = QuerySession({})
    expenses = [
        trip_exp("taxi", merchant="택시", category="transport"),
        trip_exp("manual", merchant="직접", source="manual"),
        trip_exp("gone", merchant="뺀 건", excluded=True),
    ]
    assert geocode_trip(expenses, "k", s) == {}
    assert s.calls == []


def test_is_mappable():
    assert is_mappable(trip_exp("e1"))
    assert not is_mappable(trip_exp("e1", category="transport"))
    assert not is_mappable(trip_exp("e1", source="manual"))
    assert not is_mappable(trip_exp("e1", excluded=True))


def test_trip_reuses_one_session(monkeypatch):
    created: list[QuerySession] = []

    class ClosableSession(QuerySession):
        closed = False

        def close(self) -> None:
            self.closed = True

    def make_session() -> ClosableSession:
        s = ClosableSession({})
        created.append(s)
        return s

    monkeypatch.setattr(requests, "Session", make_session)
    geocode_trip([trip_exp("e1", merchant="a"), trip_exp("e2", merchant="b")], "k")
    assert len(created) == 1 and created[0].closed and len(created[0].calls) == 2


def test_trip_without_key_makes_no_request():
    s = QuerySession({})
    assert geocode_trip([trip_exp("e1", merchant="a")], "  ", s) == {}
    assert s.calls == []


def test_strips_api_key_whitespace():
    s = fake_session({"address.json": {"documents": [{"x": "1", "y": "2"}]}})
    geocode(mk(address="x"), "  abc\n", s)
    assert s.last_headers["Authorization"] == "KakaoAK abc"


def test_blank_api_key_makes_no_request():
    s = fake_session({"address.json": {"documents": [{"x": "1", "y": "2"}]}})
    assert geocode(mk(address="x"), "   ", s) is None
    assert s.calls == []


@pytest.mark.parametrize(
    ("x", "y"),
    [
        ("126.3", "91"),
        ("126.3", "-90.5"),
        ("180.1", "33.4"),
        ("-181", "33.4"),
        ("126.3", "nan"),
        ("inf", "33.4"),
    ],
)
def test_rejects_out_of_range_or_non_finite_coordinates(x, y):
    s = fake_session({"address.json": {"documents": [{"x": x, "y": y}]}})
    assert geocode(mk(address="x", merchant=" "), "k", s) is None


def test_accepts_boundary_coordinates():
    s = fake_session({"address.json": {"documents": [{"x": "-180", "y": "90"}]}})
    assert geocode(mk(address="x"), "k", s) == (90.0, -180.0)
