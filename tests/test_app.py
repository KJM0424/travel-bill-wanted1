from streamlit.testing.v1 import AppTest

from tests.ui_helpers import APP_PATH, exp, fill_setup, open_app, open_app_with_trip


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
