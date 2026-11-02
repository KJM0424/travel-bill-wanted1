"""상용 앱 수준 마감: 여백 체계, 카드 깊이, 터치 영역, 스켈레톤, 빈 화면, 스마트 기본값, 토스트, PWA, 색."""

import json
import re
import tomllib
from datetime import date, datetime
from pathlib import Path

import pytest

from core.geocode import GeoResult
from tests.ui_helpers import exp, open_app, open_app_with_trip
from ui import map_view
from ui.layout import COLUMN_CSS

ROOT = Path(__file__).parent.parent


def css_rule(selector: str) -> str:
    """선택자가 (여러 선택자를 묶은 것 포함) 처음 나오는 규칙의 본문."""
    css = re.sub(r"/\*.*?\*/", "", COLUMN_CSS, flags=re.DOTALL)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in [s.strip() for s in selectors.split(",")]:
            return body
    raise AssertionError(selector)


# --- 3. 시각적 세련됨 ---


def test_spacing_follows_8px_grid():
    # padding·margin·gap에 쓰는 px 값은 8의 배수다. 4px는 칩 사이처럼 촘촘한 곳에만 쓰는 반 칸이다.
    values = []
    for value in re.findall(r"(?:padding|margin|gap)[\w-]*:\s*([^;]+);", COLUMN_CSS):
        values += [int(n) for n in re.findall(r"(-?\d+)px", value)]
    off_grid = sorted({v for v in values if abs(v) not in (0, 4) and v % 8})
    assert off_grid == []


def test_cards_use_background_and_soft_shadow_instead_of_borders():
    shadow = re.search(r"--tv-shadow:\s*([^;]+);", COLUMN_CSS).group(1)
    alphas = [float(a) for a in re.findall(r"rgba\([^)]*,\s*([\d.]+)\)", shadow)]
    assert alphas and all(a < 0.05 for a in alphas)
    for selector in ('[class*="st-key-sec_"]', ".tv-story", '[class*="st-key-tr_"]'):
        rule = css_rule(selector)
        assert "var(--tv-shadow)" in rule and "border: 1px" not in rule, selector


def test_page_background_matches_theme_token():
    theme = tomllib.loads((ROOT / ".streamlit/config.toml").read_text())["theme"]
    token = re.search(r"--tv-bg:\s*(#[0-9A-Fa-f]{6});", COLUMN_CSS).group(1)
    assert theme["backgroundColor"].lower() == token.lower()


# --- 1. 조작감 ---


@pytest.mark.parametrize(
    "selector",
    [
        '.st-key-page [data-testid="stButtonGroup"] button',
        '.st-key-page [data-testid="stBaseButton-tertiary"]',
        '.st-key-page [data-testid="stExpander"] summary',
    ],
)
def test_small_controls_get_44px_touch_area(selector):
    assert "min-height: 44px" in css_rule(selector)


def test_pull_to_refresh_is_blocked_because_reload_loses_the_trip():
    assert "overscroll-behavior-y: none" in css_rule("html")


def test_map_shows_skeleton_instead_of_spinner(monkeypatch):
    def no_spinner(*args, **kwargs):
        raise AssertionError("지도에서 스피너를 쓰지 않는다")

    monkeypatch.setattr(map_view.st, "spinner", no_spinner)
    monkeypatch.setattr(
        map_view,
        "geocode_trip",
        lambda es, key: {e.expense_id: GeoResult((33.4, 126.3)) for e in es},
    )
    monkeypatch.setattr(map_view, "kakao_api_key", lambda: "k")
    e = exp(10000, "A", ["A"], id="e1").model_copy(
        update={"source": "ai", "merchant_address": "제주", "paid_at": datetime(2026, 10, 10, 12)}
    )
    at = open_app_with_trip(monkeypatch, expenses=[e], step="정산")
    at.segmented_control(key="result_view").set_value("여행 돌아보기").run()
    assert not at.exception


def test_skeleton_respects_reduced_motion():
    assert "tv-skel" in map_view.SKELETON_HTML
    assert ".tv-skel" in COLUMN_CSS and "prefers-reduced-motion" in COLUMN_CSS


# --- 2. 사람 맞춤형 UX ---


def test_empty_review_speaks_to_this_trip_and_offers_next_step(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[], step="검토")
    texts = " ".join(m.value for m in at.markdown)
    assert "제주" in texts and "첫 영수증" in texts and "3명" in texts
    at.button(key="empty_upload").click().run()
    assert at.session_state["step"] == "업로드"


def test_no_transfer_state_explains_why(monkeypatch):
    expenses = [exp(10000, p, ["A", "B", "C"], id=f"e{p}") for p in ("A", "B", "C")]
    at = open_app_with_trip(monkeypatch, expenses=expenses, step="정산")
    assert any("모두 쓴 만큼 냈어요" in m.value for m in at.markdown)


def test_manual_date_defaults_to_last_payment_day(monkeypatch):
    late = exp(5000, "A", ["A"], id="late", paid_at=datetime(2026, 10, 12, 9), time_known=True)
    early = exp(5000, "A", ["A"], id="early", paid_at=datetime(2026, 10, 10, 9), time_known=True)
    at = open_app_with_trip(monkeypatch, expenses=[early, late])
    assert at.date_input(key="manual_date").value == date(2026, 10, 12)


def test_moving_start_after_end_pulls_end_along(monkeypatch):
    at = open_app(monkeypatch)
    at.date_input(key="setup_start").set_value(date(2026, 10, 10)).run()
    at.date_input(key="setup_end").set_value(date(2026, 10, 12)).run()
    at.date_input(key="setup_start").set_value(date(2026, 10, 15)).run()
    assert at.date_input(key="setup_end").value == date(2026, 10, 15)


# --- 4. 상용 서비스 마감 ---


def test_manual_add_confirms_with_toast(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(1000, "A", ["A"])])
    at.text_input(key="manual_merchant").input("주차비")
    at.number_input(key="manual_amount").set_value(5000)
    at.button(key="manual_add").click().run()
    assert [t.value for t in at.toast] == ["주차비 5,000원을 추가했어요."]


def test_flash_toast_kind_uses_toast(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(1000, "A", ["A"])])
    at.session_state["flashes"] = [("toast", "정산 파일을 불러왔어요.")]
    at.run()
    assert [t.value for t in at.toast] == ["정산 파일을 불러왔어요."]


def test_manifest_makes_it_open_like_an_app():
    manifest = json.loads((ROOT / "static/manifest.json").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone" and manifest["theme_color"] == "#17654C"
    for icon in manifest["icons"]:
        assert (ROOT / "static" / Path(icon["src"]).name).exists(), icon["src"]


def test_head_tags_link_manifest_and_ios_app_mode():
    from ui.pwa import HEAD_JS

    for needle in ("manifest", "apple-mobile-web-app-capable", "theme-color", "viewport-fit=cover"):
        assert needle in HEAD_JS
