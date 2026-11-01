import io

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from core.expense_builder import sort_expenses
from tests.ui_helpers import APP_PATH, exp, fill_setup, open_app, open_app_with_trip, trip_with
from ui import state
from ui.upload_step import process_uploads


def test_password_gate_blocks(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    at = AppTest.from_file(APP_PATH).run()
    assert at.text_input[0].label == "데모 비밀번호"
    assert not _has_button(at, "setup_save")


def test_password_gate_opens_with_right_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    at = AppTest.from_file(APP_PATH).run()
    at.text_input[0].input("pw").run()
    assert _has_button(at, "setup_save")


def test_password_gate_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    at = AppTest.from_file(APP_PATH).run()
    at.text_input[0].input("nope").run()
    assert not _has_button(at, "setup_save") and at.error


def test_setup_rejects_duplicate_members(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 민수")
    at.button(key="setup_save").click().run()
    assert "중복" in at.error[0].value
    assert "Value error" not in at.error[0].value


def test_setup_rejects_fund_wallet_name(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 회비 지갑")
    at.button(key="setup_save").click().run()
    assert "회비 지갑" in at.error[0].value and "Value error" not in at.error[0].value


def test_setup_saves_trip(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영, 철수")
    at.button(key="setup_save").click().run()
    assert at.session_state["trip"].members == ["민수", "지영", "철수"]


def test_setup_saves_fund_trip(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영", mode="회비형", fee=50000)
    at.button(key="setup_save").click().run()
    trip = at.session_state["trip"]
    assert (trip.mode, trip.fund_per_person) == ("fund", 50000)


def test_setup_resave_syncs_expenses(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(9000, "C", ["A", "B", "C"])], step="설정")
    at.text_input(key="setup_members").input("A, B").run()
    at.button(key="setup_save").click().run()
    e = at.session_state["trip"].expenses[0]
    assert (e.participants, e.payer) == (["A", "B"], "A")


def test_later_steps_need_trip(monkeypatch):
    at = open_app(monkeypatch)
    at.radio(key="step").set_value("정산").run()
    assert any("여행 설정" in i.value for i in at.info)


def test_sidebar_shows_recognizer(monkeypatch):
    at = open_app(monkeypatch)
    assert any("mock" in c.value for c in at.sidebar.caption)


def _has_button(at: AppTest, key: str) -> bool:
    return any(b.key == key for b in at.button)


# --- 업로드 단계 (Task 12) ---


@pytest.fixture
def app_session(monkeypatch):
    monkeypatch.setenv("RECOGNIZER", "mock")
    fake: dict = {"trip": trip_with([])}
    monkeypatch.setattr(state, "session", lambda: fake)
    return fake


def png(color: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 60), color).save(buffer, "PNG")
    return buffer.getvalue()


# Mock 인식기에서 white·black·gray는 영수증, red는 영수증이 아닌 사진으로 인식된다.
def test_process_uploads_adds_sorted_expenses(app_session):
    process_uploads([("a.png", png()), ("b.png", png("black")), ("c.png", png("gray"))])
    trip = app_session["trip"]
    assert len(trip.expenses) == 3 and trip.expenses == sort_expenses(trip.expenses)


def test_process_uploads_appends_not_replaces(app_session):
    process_uploads([("a.png", png())])
    first_id = app_session["trip"].expenses[0].expense_id
    process_uploads([("b.png", png("black"))])
    ids = [e.expense_id for e in app_session["trip"].expenses]
    assert len(ids) == 2 and first_id in ids


def test_process_uploads_keeps_ids_unique_across_batches(app_session):
    process_uploads([("a.png", png())])
    process_uploads([("a.png", png())])
    ids = [e.expense_id for e in app_session["trip"].expenses]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_process_uploads_over_limit_shows_notice(app_session):
    process_uploads([("a.png", png())] * 31)
    assert any("30" in n for n in app_session["upload_notices"])
    assert app_session["trip"].expenses == []


def test_process_uploads_reports_not_receipt(app_session):
    process_uploads([("cat.png", png("red"))])
    assert any("cat.png" in n for n in app_session["upload_notices"])


def test_process_uploads_uses_cache(app_session):
    process_uploads([("a.png", png())])
    assert len(app_session["recognition_cache"]) == 1


def test_process_uploads_without_key_shows_korean_error(app_session, monkeypatch):
    monkeypatch.setenv("RECOGNIZER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    process_uploads([("a.png", png())])
    assert "API 키" in app_session["upload_error"] and app_session["trip"].expenses == []


def test_upload_step_renders_notice_and_button(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[], step="업로드")
    assert any("Gemini" in c.value for c in at.caption) or any("Gemini" in i.value for i in at.info)
    assert _has_button(at, "upload_manual")
