import io
from datetime import datetime, timedelta

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from core.expense_builder import sort_expenses
from core.schema import FUND_WALLET
from tests.ui_helpers import APP_PATH, exp, fill_setup, open_app, open_app_with_trip, trip_with
from ui import state
from ui.result_step import export_trip, import_trip
from ui.review_step import add_manual_expense, expense_labels
from ui.setup_step import load_trip_file
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


# --- 검토 단계 (Task 13) ---

prepaid_trip = trip_with([])
DUP_TIME = datetime(2026, 10, 11, 15, 2)
dup_a = exp(
    18000, "A", ["A", "B", "C"], id="d1", merchant="카페", paid_at=DUP_TIME, time_known=True
)
dup_b = exp(
    18000,
    "A",
    ["A", "B", "C"],
    id="d2",
    merchant="카페",
    paid_at=DUP_TIME + timedelta(minutes=5),
    time_known=True,
)


def test_add_manual_expense_defaults():
    t = add_manual_expense(prepaid_trip, "주차비", 4000, None)
    e = t.expenses[-1]
    assert (e.source, e.payer, e.participants, e.amount) == ("manual", "A", ["A", "B", "C"], 4000)


def test_add_manual_expense_fund_payer_is_wallet():
    t = add_manual_expense(trip_with([], mode="fund", fee=10000), "주차비", 4000, None)
    assert t.expenses[-1].payer == FUND_WALLET


def test_add_manual_expense_ids_unique():
    t = add_manual_expense(prepaid_trip, "주차비", 4000, None)
    t = add_manual_expense(t, "주차비", 4000, None)
    assert len({e.expense_id for e in t.expenses}) == 2


def test_add_manual_expense_does_not_change_original():
    add_manual_expense(prepaid_trip, "주차비", 4000, None)
    assert prepaid_trip.expenses == []


def test_expense_labels_distinguish_same_merchant():
    labels = expense_labels(trip_with([dup_a, dup_b]))
    assert labels["d1"] != labels["d2"] and "카페" in labels["d1"]


def test_expense_labels_plain_when_unique():
    assert expense_labels(trip_with([exp(1000, "A", ["A"], merchant="편의점")]))["e1"] == "편의점"


def test_review_unchecking_member_updates_participants(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(18000, "A", ["A", "B", "C"], id="cafe")])
    at.checkbox(key="part_cafe_C").uncheck().run()
    assert at.session_state["trip"].expenses[0].participants == ["A", "B"]


def test_review_change_payer_and_amount(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(18000, "A", ["A", "B", "C"], id="cafe")])
    at.selectbox(key="rv_payer_cafe").set_value("B").run()
    at.number_input(key="rv_amount_cafe").set_value(20000).run()
    e = at.session_state["trip"].expenses[0]
    assert (e.payer, e.amount) == ("B", 20000)


def test_review_fund_payer_options_include_wallet(monkeypatch):
    at = open_app_with_trip(
        monkeypatch,
        expenses=[exp(18000, FUND_WALLET, ["A", "B", "C"], id="cafe")],
        mode="fund",
        fee=10000,
    )
    assert FUND_WALLET in at.selectbox(key="rv_payer_cafe").options


def test_review_exclude(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[dup_a, dup_b])
    at.checkbox(key="excl_d2").check().run()
    assert at.session_state["trip"].expenses[1].excluded


def test_review_shows_duplicate_warning(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[dup_a, dup_b])
    assert any("중복" in w.value for w in at.warning)


def test_review_shows_expense_warnings(monkeypatch):
    e = exp(18000, "A", ["A"], id="w").model_copy(update={"warnings": ["합계와 품목 합이 다름"]})
    at = open_app_with_trip(monkeypatch, expenses=[e])
    assert any("합계와 품목 합이 다름" in w.value for w in at.warning)


def test_review_manual_add_form(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[])
    at.text_input(key="manual_merchant").input("주차비")
    at.number_input(key="manual_amount").set_value(4000)
    at.button(key="manual_add").click().run()
    e = at.session_state["trip"].expenses[-1]
    assert (e.merchant_name, e.amount, e.source) == ("주차비", 4000, "manual")


def test_review_manual_add_requires_merchant_and_amount(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[])
    at.button(key="manual_add").click().run()
    assert at.error and at.session_state["trip"].expenses == []


def test_review_render_alone_does_not_change_trip(monkeypatch):
    expenses = [dup_a, exp(5000, "A", ["A", "B"], id="no-date")]
    at = open_app_with_trip(monkeypatch, expenses=expenses)
    at.run()
    assert at.session_state["trip"].expenses == expenses


# --- 정산 결과 단계 (Task 14) ---


def prepaid_trip_with_expenses():
    return trip_with(
        [
            exp(30000, "A", ["A", "B", "C"], id="e1", paid_at=DUP_TIME, time_known=True),
            exp(9000, "B", ["A", "B"], id="e2", merchant="카페"),
        ]
    )


def test_export_import_roundtrip():
    t = prepaid_trip_with_expenses()
    assert import_trip(export_trip(t)) == t


@pytest.mark.parametrize("data", [b"", b"{}", b"not json", b'{"name": 1}', b"\xff\xfe"])
def test_import_rejects_bad_file(data):
    with pytest.raises(ValueError, match="불러올 수 없는"):
        import_trip(data)


def test_result_blocked_when_not_ready(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(0, "A", ["A"])], step="정산")
    assert any("금액이 0원" in e.value for e in at.error) and not at.dataframe
    assert any(b.key == "result_back" for b in at.button)


def test_result_blocked_when_participants_empty(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(1000, "A", [])], step="정산")
    assert any("참석자가 없습니다" in e.value for e in at.error) and not at.exception


def test_result_errors_distinguish_same_merchant(monkeypatch):
    expenses = [dup_a, dup_b.model_copy(update={"amount": 0})]
    at = open_app_with_trip(monkeypatch, expenses=expenses, step="정산")
    assert any("#2" in e.value and "금액이 0원" in e.value for e in at.error)


def test_result_shows_table_and_messages(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    assert at.dataframe and sum("10,000원" in c.value for c in at.code) == 2


def test_result_fund_leader_shortfall_shown_separately(monkeypatch):
    at = open_app_with_trip(
        monkeypatch,
        expenses=[exp(36000, FUND_WALLET, ["A", "B", "C"])],
        step="정산",
        mode="fund",
        fee=10000,
    )
    assert len(at.code) == 2 and not any("A님 →" in c.value for c in at.code)
    assert any("대표가 직접 채울 금액" in i.value and "2,000원" in i.value for i in at.info)


def test_result_fund_leader_refund_shown_separately(monkeypatch):
    at = open_app_with_trip(
        monkeypatch,
        expenses=[exp(24000, FUND_WALLET, ["A", "B", "C"])],
        step="정산",
        mode="fund",
        fee=10000,
    )
    assert len(at.code) == 2 and not any("A님께" in c.value for c in at.code)
    assert any("대표" in i.value and "2,000원" in i.value for i in at.info)


def test_result_has_download_button(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    assert at.get("download_button")


def test_load_trip_file_replaces_trip_and_resets_widgets(app_session):
    app_session["setup_members"] = "옛날 값"
    app_session["part_e1_A"] = False
    loaded = prepaid_trip_with_expenses()
    assert load_trip_file(export_trip(loaded)) is None
    assert app_session["trip"] == loaded
    assert "setup_members" not in app_session and "part_e1_A" not in app_session


def test_load_trip_file_bad_file_keeps_trip(app_session):
    before = app_session["trip"]
    assert "불러올 수 없는" in load_trip_file(b"not json")
    assert app_session["trip"] is before


def test_review_card_title_shows_number_once(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[dup_a, dup_b])
    titles = [m.value for m in at.markdown if "카페" in m.value]
    assert titles and not any(t.count("#2") > 1 or t.count("#1") > 1 for t in titles)


def test_setup_readding_member_checks_them_on_existing_expenses(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(9000, "A", ["A", "B", "C"])], step="설정")
    at.text_input(key="setup_members").input("A, B").run()
    at.button(key="setup_save").click().run()
    at.text_input(key="setup_members").input("A, B, C").run()
    at.button(key="setup_save").click().run()
    assert at.session_state["trip"].expenses[0].participants == ["A", "B", "C"]
    assert any("C" in i.value and "추가" in i.value for i in at.info)


def test_setup_removing_member_is_reported(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(9000, "A", ["A", "B", "C"])], step="설정")
    at.text_input(key="setup_members").input("A, B").run()
    at.button(key="setup_save").click().run()
    assert any("C" in i.value and "뺐" in i.value for i in at.info)


def test_import_rejects_duplicate_expense_ids():
    t = trip_with([exp(1000, "A", ["A"], id="x"), exp(2000, "A", ["A"], id="x")])
    with pytest.raises(ValueError, match="불러올 수 없는"):
        import_trip(export_trip(t))


# --- PR #4에서 넘어온 Minor ---


def test_load_trip_file_clears_previous_upload_notices(app_session):
    app_session["upload_notices"] = ["a.png: 영수증이 아니어서 제외했습니다."]
    app_session["upload_error"] = "오류"
    app_session["upload_added"] = 2
    assert load_trip_file(export_trip(prepaid_trip_with_expenses())) is None
    assert not app_session.get("upload_notices")
    assert not app_session.get("upload_error") and not app_session.get("upload_added")


def test_setup_allows_trailing_comma_in_members(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영,")
    at.button(key="setup_save").click().run()
    assert at.session_state["trip"].members == ["민수", "지영"]


def test_setup_still_rejects_empty_name_between_commas(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수,, 지영")
    at.button(key="setup_save").click().run()
    assert at.error and "trip" not in at.session_state
