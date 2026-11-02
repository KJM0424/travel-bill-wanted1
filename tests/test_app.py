import io
from datetime import date, datetime, timedelta

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from core.expense_builder import sort_expenses
from core.geocode import GeoResult
from core.schema import FUND_WALLET, Expense
from tests.ui_helpers import APP_PATH, exp, fill_setup, open_app, open_app_with_trip, trip_with
from ui import map_view, state
from ui.map_view import Stop, build_route_map, story_html
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
    assert _has_button(at, "start_begin")


def test_password_gate_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    at = AppTest.from_file(APP_PATH).run()
    at.text_input[0].input("nope").run()
    assert not _has_button(at, "setup_save") and at.error


def test_setup_rejects_duplicate_members(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 민수")
    at.button(key="setup_save").click().run()
    assert "두 번" in at.error[0].value
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
    at.session_state["step"] = "정산"
    at.run()
    assert any("여행 정보" in i.value for i in at.info)


def _has_button(at: AppTest, key: str) -> bool:
    return any(b.key == key for b in at.button)


def _open_editor(at: AppTest, eid: str) -> AppTest:
    """검토 화면의 결제 행을 펼쳐 수정 칸을 연다."""
    return at.button(key=f"rv_open_{eid}").click().run()


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


def test_process_uploads_skips_non_image_files_with_notice(app_session):
    process_uploads([("receipt.pdf", b"%PDF-1.4"), ("a.png", png())])
    assert (
        "receipt.pdf: 이미지 파일만 올릴 수 있어요 (JPG·PNG·HEIC)" in app_session["upload_notices"]
    )
    assert len(app_session["trip"].expenses) == 1
    assert len(app_session["recognition_cache"]) == 1


def test_process_uploads_only_non_images_adds_nothing(app_session):
    process_uploads([("memo.txt", b"hello"), ("receipt.PDF", b"%PDF-1.4")])
    notices = app_session["upload_notices"]
    assert len(notices) == 2 and all("이미지 파일만 올릴 수 있어요" in n for n in notices)
    assert app_session["trip"].expenses == [] and app_session["upload_added"] == 0


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
    _open_editor(at, "cafe")
    at.pills(key="part_cafe").set_value(["A", "B"]).run()
    assert at.session_state["trip"].expenses[0].participants == ["A", "B"]


def test_review_editor_is_closed_until_row_opened(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(18000, "A", ["A", "B", "C"], id="cafe")])
    assert not any(n.key == "rv_amount_cafe" for n in at.number_input)
    _open_editor(at, "cafe")
    assert at.number_input(key="rv_amount_cafe").value == 18000
    at.button(key="rv_open_cafe").click().run()
    assert not any(n.key == "rv_amount_cafe" for n in at.number_input)


def test_review_shows_total_and_date_group(monkeypatch):
    at = open_app_with_trip(
        monkeypatch,
        expenses=[exp(18000, "A", ["A", "B"], id="cafe", paid_at=datetime(2026, 10, 11, 15, 2))],
    )
    texts = " ".join(m.value for m in [*at.markdown, *at.caption])
    assert "18,000원" in texts and "1건" in texts and "10월 11일" in texts


def test_review_change_payer_and_amount(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(18000, "A", ["A", "B", "C"], id="cafe")])
    _open_editor(at, "cafe")
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
    _open_editor(at, "cafe")
    assert FUND_WALLET in at.selectbox(key="rv_payer_cafe").options


def test_review_exclude(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[dup_a, dup_b])
    _open_editor(at, "d2")
    at.toggle(key="excl_d2").set_value(True).run()
    assert at.session_state["trip"].expenses[1].excluded


def test_review_shows_duplicate_warning(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[dup_a, dup_b])
    assert any("두 번" in w.value for w in at.warning)


def test_review_shows_expense_warnings(monkeypatch):
    e = exp(18000, "A", ["A"], id="w").model_copy(update={"warnings": ["합계와 품목 합이 다름"]})
    at = open_app_with_trip(monkeypatch, expenses=[e])
    texts = [m.value for m in [*at.caption, *at.markdown]]
    assert any("합계와 품목 합이 다름" in t for t in texts)


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
    assert any("함께한 사람이 없어요" in e.value for e in at.error) and not at.exception


def test_result_errors_distinguish_same_merchant(monkeypatch):
    expenses = [dup_a, dup_b.model_copy(update={"amount": 0})]
    at = open_app_with_trip(monkeypatch, expenses=expenses, step="정산")
    assert any("#2" in e.value and "금액이 0원" in e.value for e in at.error)


def test_result_shows_table_and_messages(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    assert sum("10,000원" in c.value for c in at.code) == 2
    assert open_people_tab(at).dataframe


def open_people_tab(at: AppTest) -> AppTest:
    return at.segmented_control(key="result_view").set_value("사람별 정산").run()


def test_result_fund_leader_shortfall_shown_separately(monkeypatch):
    at = open_app_with_trip(
        monkeypatch,
        expenses=[exp(36000, FUND_WALLET, ["A", "B", "C"])],
        step="정산",
        mode="fund",
        fee=10000,
    )
    assert len(at.code) == 2 and not any("A님 →" in c.value for c in at.code)
    assert any(
        "모자라요" in i.value and "총무" in i.value and "2,000원" in i.value for i in at.info
    )


def test_result_fund_leader_refund_shown_separately(monkeypatch):
    at = open_app_with_trip(
        monkeypatch,
        expenses=[exp(24000, FUND_WALLET, ["A", "B", "C"])],
        step="정산",
        mode="fund",
        fee=10000,
    )
    assert len(at.code) == 2 and not any("A님께" in c.value for c in at.code)
    assert any(
        "남았어요" in i.value and "총무" in i.value and "2,000원" in i.value for i in at.info
    )


def test_result_has_download_button(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    assert at.get("download_button")


def test_load_trip_file_replaces_trip_and_resets_widgets(app_session):
    app_session["setup_members"] = "옛날 값"
    app_session["part_e1"] = ["B"]
    loaded = prepaid_trip_with_expenses()
    assert load_trip_file(export_trip(loaded)) is None
    assert app_session["trip"] == loaded
    assert "setup_members" not in app_session and "part_e1" not in app_session


def test_load_trip_file_bad_file_keeps_trip(app_session):
    before = app_session["trip"]
    assert "불러올 수 없는" in load_trip_file(b"not json")
    assert app_session["trip"] is before


def test_review_card_title_shows_number_once(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[dup_a, dup_b])
    # 같은 상호는 시각으로 구분한다. 내부 순번(#1, #2)은 화면에 보이지 않는다.
    titles = [m.value for m in at.markdown if "카페" in m.value]
    assert titles and not any("#" in t for t in titles)


def test_setup_readding_member_checks_them_on_existing_expenses(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(9000, "A", ["A", "B", "C"])], step="설정")
    at.text_input(key="setup_members").input("A, B").run()
    at.button(key="setup_save").click().run()
    at.button(key="nav_back").click().run()
    at.text_input(key="setup_members").input("A, B, C").run()
    at.button(key="setup_save").click().run()
    assert at.session_state["trip"].expenses[0].participants == ["A", "B", "C"]
    assert any("C" in i.value and "넣었어요" in i.value for i in at.info)


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


def test_review_date_change_resorts_expenses(monkeypatch):
    first = exp(1000, "A", ["A"], id="x1", merchant="아침", paid_at=DUP_TIME, time_known=True)
    second = exp(
        2000,
        "A",
        ["A"],
        id="x2",
        merchant="저녁",
        paid_at=DUP_TIME + timedelta(hours=5),
        time_known=True,
    )
    at = open_app_with_trip(monkeypatch, expenses=[first, second])
    _open_editor(at, "x2")
    at.date_input(key="rv_date_x2").set_value((DUP_TIME - timedelta(days=1)).date()).run()
    assert [e.expense_id for e in at.session_state["trip"].expenses] == ["x2", "x1"]


def test_load_trip_file_clears_previous_upload_notices(app_session):
    app_session["upload_notices"] = ["a.png: 영수증이 아니어서 제외했어요."]
    app_session["upload_error"] = "오류"
    app_session["upload_added"] = 2
    assert load_trip_file(export_trip(prepaid_trip_with_expenses())) is None
    assert not app_session.get("upload_notices")
    assert not app_session.get("upload_error") and not app_session.get("upload_added")


def test_review_unchecking_time_unknown_does_not_set_midnight(monkeypatch):
    no_time = exp(1000, "A", ["A"], id="t", paid_at=datetime(2026, 10, 11), time_known=False)
    at = open_app_with_trip(monkeypatch, expenses=[no_time])
    _open_editor(at, "t")
    at.checkbox(key="rv_notime_t").uncheck().run()
    assert at.session_state["trip"].expenses[0].time_known is False
    at.time_input(key="rv_time_t").set_value(datetime(2026, 10, 11, 9, 30).time()).run()
    e = at.session_state["trip"].expenses[0]
    assert e.time_known and e.paid_at == datetime(2026, 10, 11, 9, 30)


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


def test_review_many_members_do_not_use_one_column_each(monkeypatch):
    members = ["A", *(f"친구{i}" for i in range(9))]
    at = open_app_with_trip(
        monkeypatch, expenses=[exp(10000, "A", members, id="m")], members=members
    )
    _open_editor(at, "m")
    # 사람 수만큼 칸을 나누면 칸이 좁아져 이름이 글자 단위로 줄바꿈된다.
    in_columns = [w for col in at.columns for w in col.children.values()]
    assert not any(str(getattr(w, "key", "")).startswith("part_") for w in in_columns)
    assert at.pills(key="part_m").value == members


def test_setup_leader_follows_member_changes(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="A, B")
    at.text_input(key="setup_members").input("B, C").run()
    leader = at.pills(key="setup_leader")
    assert (leader.options, leader.value) == (["B", "C"], "B")
    at.button(key="setup_save").click().run()
    assert at.session_state["trip"].leader == "B"


def test_setup_leader_keeps_choice_when_members_grow(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="A, B")
    at.pills(key="setup_leader").set_value("B").run()
    at.text_input(key="setup_members").input("A, B, C").run()
    at.button(key="setup_save").click().run()
    assert at.session_state["trip"].leader == "B"


# --- 화면 다듬기: 시작 화면·진행 표시·주요 버튼 ---


def test_start_screen_shows_name_and_one_start_button(monkeypatch):
    from ui.branding import APP_NAME

    monkeypatch.setenv("RECOGNIZER", "mock")
    monkeypatch.setenv("APP_PASSWORD", "")
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert any(APP_NAME in m.value for m in at.markdown)
    assert [b.key for b in at.button if b.proto.type == "primary"] == ["start_begin"]
    at.button(key="start_begin").click().run()
    assert _has_button(at, "setup_save")


def test_screens_do_not_show_recognizer_name(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[], step="업로드")
    texts = [e.value for e in [*at.caption, *at.markdown, *at.info]]
    assert not any("인식기" in t for t in texts)


def test_upload_notice_says_local_when_ollama(monkeypatch):
    monkeypatch.setenv("RECOGNIZER", "ollama")
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.session_state["trip"] = trip_with([])
    at.session_state["step"] = "업로드"
    at.run()
    captions = [c.value for c in at.caption]
    assert any("이 컴퓨터" in c for c in captions)
    assert not any("Gemini" in c for c in captions)


def test_mock_badge_only_when_mock(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[], step="업로드")
    assert any("체험 모드" in m.value for m in at.markdown)
    monkeypatch.setenv("RECOGNIZER", "gemini")
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.session_state["trip"] = trip_with([])
    at.session_state["step"] = "업로드"
    at.run()
    assert not any("체험 모드" in m.value for m in at.markdown)


@pytest.mark.parametrize(
    ("step", "label"),
    [("설정", "1/4"), ("업로드", "2/4"), ("검토", "3/4"), ("정산", "4/4")],
)
def test_progress_shows_step(monkeypatch, step, label):
    at = open_app_with_trip(monkeypatch, expenses=[exp(9000, "A", ["A", "B", "C"])], step=step)
    assert any(label in c.value for c in at.caption)
    assert not at.get("progress")


def test_setup_save_moves_to_upload(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영")
    at.button(key="setup_save").click().run()
    assert at.session_state["step"] == "업로드"


def test_back_button_goes_to_previous_step(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[], step="업로드")
    at.button(key="nav_back").click().run()
    assert at.session_state["step"] == "설정"


def test_each_step_has_one_primary_button(monkeypatch):
    for step in ["설정", "업로드", "검토"]:
        at = open_app_with_trip(monkeypatch, expenses=[exp(9000, "A", ["A", "B", "C"])], step=step)
        assert len([b for b in at.button if b.proto.type == "primary"]) == 1, step


def test_result_shows_person_cards(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    open_people_tab(at)
    texts = " ".join(m.value for m in [*at.markdown, *at.caption])
    assert "받을 돈" in texts and "보낼 돈" in texts and "20,000원" in texts


def test_result_person_card_says_my_share(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    open_people_tab(at)
    captions = [c.value for c in at.caption]
    assert "낸 돈 30,000원, 나눌 몫 10,000원" in captions
    assert not any("쓴 돈" in c for c in captions)


def test_transfer_message_starts_with_app_name(monkeypatch):
    from ui.branding import APP_NAME

    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    assert at.code and all(c.value.splitlines()[0] == f"[{APP_NAME}]" for c in at.code)


# --- 경로 지도 (Task 18) ---


def place(id: str, merchant: str, hour: int, address: str | None = None, **kwargs) -> Expense:
    return Expense(
        expense_id=id,
        source="ai",
        merchant_name=merchant,
        merchant_address=address,
        paid_at=datetime(2026, 10, 10, hour),
        time_known=True,
        amount=10000,
        payer="A",
        participants=["A", "B"],
        **kwargs,
    )


class FakeGeocoder:
    """geocode_trip 대신 고정 결과를 돌려주고, 무엇을 물었는지 기록한다."""

    def __init__(self, results: dict[str, GeoResult]):
        self.results = results
        self.asked: list[list[str]] = []

    def __call__(self, expenses, api_key, session=None):
        self.asked.append([e.expense_id for e in expenses])
        return {e.expense_id: self.results[e.expense_id] for e in expenses}


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def open_map(monkeypatch, expenses: list[Expense], results: dict[str, GeoResult], key: str = "k"):
    fake = FakeGeocoder(results)
    monkeypatch.setattr(map_view, "geocode_trip", fake)
    monkeypatch.setattr(map_view, "kakao_api_key", lambda: key)
    at = open_app_with_trip(monkeypatch, expenses=expenses, step="정산")
    return at.segmented_control(key="result_view").set_value("여행 돌아보기").run(), fake


def all_text(at: AppTest) -> str:
    elements = [*at.markdown, *at.caption, *at.info, *at.warning, *at.subheader]
    return " ".join(e.value for e in elements)


def stop(name: str, day: int, lat: float = 33.4, lng: float = 126.3, **kwargs) -> Stop:
    fields = {"category": "food", "when": "10월 10일 12:00", "amount": 30000, "people": "모두"}
    return Stop(name=name, lat=lat, lng=lng, day=day, **(fields | kwargs))


def test_route_map_colors_each_day_and_uses_category_icons():
    stops = [
        stop("흑돼지", 0),
        stop("카페", 0, 33.5, 126.5, category="cafe"),
        stop("호텔", 1, 33.25, 126.4, category="lodging"),
    ]
    html = build_route_map(stops).get_root().render()
    assert "antPath" in html
    assert map_view.DAY_COLORS[0] in html and map_view.DAY_COLORS[1] in html
    assert "fa-utensils" in html and "fa-mug-hot" in html and "fa-bed" in html


def test_route_map_joins_days_with_dashed_line():
    html = build_route_map([stop("흑돼지", 0), stop("호텔", 1, 33.25, 126.4)]).get_root().render()
    assert '"dashArray": "6 8"' in html


def test_route_map_popup_shows_time_amount_and_people():
    html = build_route_map([stop("흑돼지", 0, people="A, B")]).get_root().render()
    assert "10월 10일 12:00" in html and "30,000원" in html and "A, B" in html


def test_route_map_has_replay_button():
    html = build_route_map([stop("흑돼지", 0), stop("카페", 0, 33.5, 126.5)]).get_root().render()
    assert map_view.REPLAY_LABEL in html


def test_route_map_single_stop_has_no_replay():
    html = build_route_map([stop("흑돼지", 0)]).get_root().render()
    assert map_view.REPLAY_LABEL not in html


def test_render_map_without_key_shows_info(monkeypatch):
    at, fake = open_map(monkeypatch, [place("e1", "흑돼지", 12)], {}, key="")
    assert any("카카오" in i.value for i in at.info)
    assert fake.asked == []


def test_render_map_lists_not_found_expenses(monkeypatch):
    expenses = [place("e1", "흑돼지", 12), place("e2", "없는가게", 15)]
    results = {"e1": GeoResult((33.4, 126.3)), "e2": GeoResult(None)}
    at, _ = open_map(monkeypatch, expenses, results)
    assert "위치를 찾지 못한 결제: 없는가게" in all_text(at)
    assert "위치를 불러오지 못했어요" not in all_text(at)


def test_render_map_all_lookups_failed_shows_load_error(monkeypatch):
    expenses = [place("e1", "흑돼지", 12), place("e2", "카페", 15)]
    results = {"e1": GeoResult(None, failed=True), "e2": GeoResult(None, failed=True)}
    at, _ = open_map(monkeypatch, expenses, results)
    assert any("위치를 불러오지 못했어요" in w.value for w in at.warning)
    assert "위치를 찾지 못한 결제" not in all_text(at)


def test_route_map_escapes_merchant_names():
    hostile = "a`b${document.title=1}<img src=x onerror=alert(2)>"
    html = build_route_map([stop(hostile, 0, people=hostile)]).get_root().render()
    assert hostile not in html and "<img src=x" not in html and "${document" not in html


def test_render_map_partial_failure_lists_both_kinds(monkeypatch):
    expenses = [place("e1", "흑돼지", 12), place("e2", "없는가게", 15)]
    results = {"e1": GeoResult(None, failed=True), "e2": GeoResult(None)}
    at, _ = open_map(monkeypatch, expenses, results)
    assert not at.warning
    text = all_text(at)
    assert "위치를 찾지 못한 결제: 없는가게" in text and "위치를 불러오지 못한 결제: 흑돼지" in text


def test_render_map_reuses_results_until_places_change(monkeypatch):
    at, fake = open_map(monkeypatch, [place("e1", "흑돼지", 12)], {"e1": GeoResult((33.4, 126.3))})
    at.run()
    assert len(fake.asked) == 1
    trip = at.session_state["trip"]
    moved = trip.expenses[0].model_copy(update={"merchant_address": "제주 서귀포시 1"})
    at.session_state["trip"] = trip.model_copy(update={"expenses": [moved]})
    at.run()
    assert len(fake.asked) == 2


@pytest.mark.parametrize(
    ("result", "wait"),
    [
        (GeoResult(None, failed=True), map_view.RETRY_FAILED_SECONDS),
        (GeoResult(None), map_view.RETRY_NOT_FOUND_SECONDS),
    ],
)
def test_render_map_retries_unresolved_only_after_wait(monkeypatch, result, wait):
    clock = Clock()
    monkeypatch.setattr(map_view, "now", clock)
    expenses = [place("e1", "흑돼지", 12), place("e2", "카페", 15)]
    at, fake = open_map(monkeypatch, expenses, {"e1": GeoResult((33.4, 126.3)), "e2": result})
    clock.value += wait - 1
    at.run()
    assert len(fake.asked) == 1
    clock.value += 2
    at.run()
    assert len(fake.asked) == 2


def test_render_map_found_results_never_expire(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(map_view, "now", clock)
    at, fake = open_map(monkeypatch, [place("e1", "흑돼지", 12)], {"e1": GeoResult((33.4, 126.3))})
    clock.value += 10**6
    at.run()
    assert len(fake.asked) == 1


def test_render_map_skips_transport_and_manual(monkeypatch):
    expenses = [
        place("e1", "흑돼지", 12),
        place("taxi", "택시", 13, category="transport"),
        exp(5000, "A", ["A"], id="m1", merchant="직접 쓴 돈"),
    ]
    at, fake = open_map(monkeypatch, expenses, {"e1": GeoResult((33.4, 126.3))})
    assert fake.asked == [["e1"]]
    assert "택시" not in all_text(at) and "직접 쓴 돈" not in all_text(at)


def test_result_summary_counts_only_included_and_escapes_name():
    from ui.result_step import summary_html

    kept = exp(30000, "A", ["A", "B", "C"], id="k")
    dropped = exp(9000, "A", ["A"], id="d").model_copy(update={"excluded": True})
    trip = trip_with([kept, dropped]).model_copy(update={"name": "<b>제주</b>"})
    html_text = summary_html(trip)
    assert "30,000원" in html_text and "1건" in html_text and "10,000원" in html_text
    assert "<b>제주</b>" not in html_text and "&lt;b&gt;" in html_text


# --- 여행 돌아보기 ---


def visit(id: str, merchant: str, day: int, hour: int, **kwargs) -> Expense:
    return place(id, merchant, hour, **kwargs).model_copy(
        update={"paid_at": datetime(2026, 10, 9 + day, hour)}
    )


def two_day_trip() -> list[Expense]:
    return [
        visit("e1", "고기국수", 1, 12),
        visit("e2", "카페", 1, 15, category="cafe"),
        visit("e3", "생선구이", 2, 19),
    ]


TWO_DAY_COORDS = {
    "e1": GeoResult((33.46, 126.31)),
    "e2": GeoResult((33.47, 126.33)),
    "e3": GeoResult((33.25, 126.41)),
}


def test_story_html_shows_trip_numbers():
    from core.trip_story import TripStats

    stats = TripStats(
        "2박 3일",
        13,
        1200000,
        (date(2026, 10, 11), 256000),
        ("<b>생선</b>", 96000),
        [("food", 60), ("lodging", 40)],
    )
    text = story_html(stats, 186.4)
    assert "2박 3일" in text and "13번" in text and "약 186km" in text
    assert "10월 11일" in text and "256,000원" in text and "96,000원" in text
    assert "식비 60%" in text and "숙소 40%" in text
    assert "<b>생선</b>" not in text and "&lt;b&gt;" in text


def test_story_html_without_distance_skips_distance_row():
    from core.trip_story import TripStats

    stats = TripStats("당일치기", 1, 10000, None, ("국수", 10000), [("food", 100)])
    assert "이동 거리" not in story_html(stats, None)


def test_story_card_shows_even_without_kakao_key(monkeypatch):
    at, _ = open_map(monkeypatch, two_day_trip(), {}, key="")
    assert any("2박 3일" in h.value for h in at.get("html"))
    assert any("카카오" in i.value for i in at.info)


def test_story_card_includes_distance_when_located(monkeypatch):
    at, _ = open_map(monkeypatch, two_day_trip(), TWO_DAY_COORDS)
    assert any("이동 거리" in h.value for h in at.get("html"))


def test_day_pills_list_trip_days(monkeypatch):
    at, _ = open_map(monkeypatch, two_day_trip(), TWO_DAY_COORDS)
    assert at.pills(key="map_day").options == ["전체", "1일차", "2일차"]


def test_timeline_lists_each_day_in_order(monkeypatch):
    at, _ = open_map(monkeypatch, two_day_trip(), TWO_DAY_COORDS)
    text = all_text(at)
    assert "고기국수 → 카페" in text and "생선구이" in text
    assert "20,000원" in text


def test_picking_a_day_draws_only_that_day(monkeypatch):
    drawn: list[list[str]] = []
    real = map_view.build_route_map

    def spy(stops):
        drawn.append([s.name for s in stops])
        return real(stops)

    monkeypatch.setattr(map_view, "build_route_map", spy)
    at, _ = open_map(monkeypatch, two_day_trip(), TWO_DAY_COORDS)
    assert drawn[-1] == ["고기국수", "카페", "생선구이"]
    at.pills(key="map_day").set_value("2일차").run()
    assert drawn[-1] == ["생선구이"]
    assert "고기국수" not in all_text(at)


def test_day_outside_trip_is_labeled_by_date(monkeypatch):
    early = visit("e0", "숙소 예약", 1, 9, category="lodging").model_copy(
        update={"paid_at": datetime(2026, 9, 28, 9)}
    )
    coords = TWO_DAY_COORDS | {"e0": GeoResult((33.5, 126.5))}
    at, _ = open_map(monkeypatch, [early, *two_day_trip()], coords)
    assert at.pills(key="map_day").options == ["전체", "9월 28일", "1일차", "2일차"]


@pytest.mark.parametrize(
    ("day", "index"),
    [(date(2026, 10, 10), 0), (date(2026, 10, 12), 2), (date(2026, 9, 28), -1), (None, -1)],
)
def test_day_index_counts_from_trip_start_and_greys_out_other_days(day, index):
    assert map_view.day_index(day, trip_with([])) == index


def test_story_bar_uses_its_own_shades_not_day_colors():
    from core.trip_story import TripStats

    stats = TripStats("2박 3일", 2, 20000, None, None, [("lodging", 60), ("food", 40)])
    text = story_html(stats, None)
    assert map_view.SHARE_COLORS[0] in text and map_view.SHARE_COLORS[1] in text
    assert not any(color in text for color in map_view.DAY_COLORS[1:])


def test_route_is_drawn_as_curves_not_straight_lines():
    m = build_route_map([stop("흑돼지", 0), stop("카페", 0, 33.5, 126.5)])
    paths = [c for c in m._children.values() if hasattr(c, "_children")]
    ant = [
        child
        for group in paths
        for child in group._children.values()
        if type(child).__name__ == "AntPath"
    ]
    assert ant and len(ant[0].locations) > 2


def test_replay_moves_a_car_along_the_route():
    html = build_route_map([stop("흑돼지", 0), stop("카페", 0, 33.5, 126.5)]).get_root().render()
    assert "fa-car-side" in html and "requestAnimationFrame" in html


# --- 총무 계좌 ---


def pay_key(name: str, field: str) -> str:
    return f"setup_pay_{name}_{field}"


def test_setup_saves_leader_bank_and_number(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영")
    at.selectbox(key=pay_key("민수", "bank")).set_value("카카오뱅크").run()
    at.text_input(key=pay_key("민수", "account_number")).input("3333 01 1234567").run()
    at.text_input(key=pay_key("민수", "account_holder")).input("김민수").run()
    at.button(key="setup_save").click().run()
    info = at.session_state["trip"].payout["민수"]
    assert (info.bank, info.account_number, info.account_holder) == (
        "카카오뱅크",
        "3333011234567",
        "김민수",
    )


def test_setup_rejects_bad_account_number(monkeypatch):
    from core.payment_message import ACCOUNT_NUMBER_ERROR

    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영")
    at.selectbox(key=pay_key("민수", "bank")).set_value("카카오뱅크").run()
    at.text_input(key=pay_key("민수", "account_number")).input("12ab").run()
    at.button(key="setup_save").click().run()
    assert any(f"민수: {ACCOUNT_NUMBER_ERROR}" == e.value for e in at.error)
    assert at.session_state["step"] == "설정"


def test_setup_needs_both_bank_and_number(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영")
    at.text_input(key=pay_key("지영", "account_number")).input("110123456789").run()
    at.button(key="setup_save").click().run()
    assert any("지영: 은행과 계좌번호를 함께 적어 주세요." == e.value for e in at.error)


def test_old_one_line_account_is_split_into_fields(monkeypatch):
    from core.schema import PayoutInfo

    monkeypatch.setenv("RECOGNIZER", "mock")
    monkeypatch.setenv("APP_PASSWORD", "")
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    old = PayoutInfo(bank_account="신한 110-123-456789 홍길동")
    at.session_state["trip"] = trip_with([]).model_copy(update={"payout": {"A": old}})
    at.session_state["step"] = "설정"
    at.run()
    assert at.selectbox(key=pay_key("A", "bank")).value == "신한은행"
    assert at.text_input(key=pay_key("A", "account_number")).value == "110-123-456789"
    assert at.text_input(key=pay_key("A", "account_holder")).value == "홍길동"


def test_transfer_has_account_copy_when_receiver_has_account():
    from core.payment_message import build_message
    from core.schema import PayoutInfo
    from core.settlement import Transfer
    from ui.result_step import transfer_copies

    trip = trip_with([]).model_copy(
        update={"payout": {"A": PayoutInfo(bank="카카오뱅크", account_number="3333011234567")}}
    )
    copies = transfer_copies(Transfer("B", "A", 1000), trip)
    assert [label for label, _ in copies] == ["메시지 복사", "계좌 복사"]
    assert copies[1][1] == "카카오뱅크 3333011234567"
    assert build_message(Transfer("B", "A", 1000), trip) in copies[0][1]
    assert [label for label, _ in transfer_copies(Transfer("A", "B", 1000), trip)] == [
        "메시지 복사"
    ]


# --- 앱처럼: 정산 화면 탭 ---

RESULT_TABS = ["보낼 돈", "사람별 정산", "여행 돌아보기"]


def test_result_starts_on_transfers_tab(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    view = at.segmented_control(key="result_view")
    assert view.options == RESULT_TABS and view.value == "보낼 돈"
    assert at.code and not at.dataframe


def test_result_people_tab_shows_people_not_transfers(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    at.segmented_control(key="result_view").set_value("사람별 정산").run()
    assert at.dataframe and not at.code


def test_map_is_looked_up_only_after_opening_trip_tab(monkeypatch):
    fake = FakeGeocoder({"e1": GeoResult((33.4, 126.3))})
    monkeypatch.setattr(map_view, "geocode_trip", fake)
    monkeypatch.setattr(map_view, "kakao_api_key", lambda: "k")
    at = open_app_with_trip(monkeypatch, expenses=[place("e1", "흑돼지", 12)], step="정산")
    assert fake.asked == []
    at.segmented_control(key="result_view").set_value("여행 돌아보기").run()
    assert fake.asked == [["e1"]]


# --- 앱처럼: 검토 화면 접기·펼치기 ---


def test_review_rows_start_folded(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])])
    assert not [p for p in at.pills if str(p.key).startswith("part_")]


def test_tapping_row_unfolds_and_tapping_again_folds(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])])
    at.button(key="rv_open_e1").click().run()
    assert at.pills(key="part_e1").value == ["A", "B", "C"]
    assert at.text_input(key="rv_name_e1").value == "가게"
    at.button(key="rv_open_e1").click().run()
    assert not [p for p in at.pills if str(p.key).startswith("part_")]


@pytest.mark.parametrize(
    ("participants", "who"), [(["A", "B", "C"], "3명 모두"), (["A", "C"], "A, C")]
)
def test_folded_row_says_who_joined(monkeypatch, participants, who):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", participants)])
    assert any(who in c.value for c in at.caption)


# --- 앱처럼: 설정 화면 ---


def test_setup_shows_trip_length(monkeypatch):
    from datetime import date as d

    at = open_app(monkeypatch)
    at.date_input(key="setup_start").set_value(d(2026, 10, 10)).run()
    at.date_input(key="setup_end").set_value(d(2026, 10, 12)).run()
    assert any("2박 3일" in m.value for m in [*at.markdown, *at.caption])


def test_setup_counts_members_as_typed(monkeypatch):
    at = open_app(monkeypatch)
    at.text_input(key="setup_members").input("민수, 지영, 철수").run()
    assert any("3명" in m.value for m in [*at.markdown, *at.caption])


# --- 문구 검토(2026-11-02) ---


def test_upload_failure_box_does_not_miscount_grouped_files(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[], step="업로드")
    at.session_state["upload_notices"] = [
        "a.jpg 외 12장: 읽지 못했어요. 이유. 직접 추가할 수도 있어요."
    ]
    at.run()
    titles = [w.proto.title for w in at.warning]
    assert "결제로 넣지 못한 사진이 있어요" in titles and not any("1장" in t for t in titles)


def test_start_screen_says_to_tap_payment_first(monkeypatch):
    from ui.start_step import STEPS_HTML

    assert "결제를 눌러" in STEPS_HTML and "이름만 누르면" not in STEPS_HTML


def test_setup_first_card_asks_about_the_trip(monkeypatch):
    at = open_app(monkeypatch)
    texts = [m.value for m in [*at.markdown, *at.caption]]
    assert "#### 어떤 여행이었나요?" in texts
    assert not any("네 가지" in t for t in texts)


def test_setup_added_member_notice_points_to_payment_list(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="설정")
    at.text_input(key="setup_members").input("A, B, C, D").run()
    at.button(key="setup_save").click().run()
    notes = " ".join(i.value for i in at.info)
    assert "결제 내역에서 빼 주세요" in notes and "체크" not in notes


def test_setup_removed_payer_notice_says_leader_took_over(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "C", ["A", "B", "C"])], step="설정")
    at.text_input(key="setup_members").input("A, B").run()
    at.button(key="setup_save").click().run()
    notes = " ".join(i.value for i in at.info)
    assert "C님이 결제한 건은 총무 A님이 낸 것으로 바꿨어요" in notes


def test_map_popup_says_how_many_joined():
    from ui.map_view import _stop

    e = place("e1", "흑돼지", 12)
    trip = trip_with([e], members=["A", "B"])
    assert _stop(e, (33.4, 126.3), 0, trip).people == "2명 모두"


def test_start_screen_lists_four_steps_including_trip_review():
    from ui.start_step import STEPS_HTML

    assert STEPS_HTML.count("<li>") == 4
    assert "여행을 돌아봐요" in STEPS_HTML and "지도" in STEPS_HTML


def test_row_toggle_button_is_stretched_over_the_whole_row():
    # Streamlit이 버튼 칸에 글자 너비를 넣어서, 너비를 강제하지 않으면 금액·화살표 쪽이 눌리지 않았다.
    import re

    from ui.layout import COLUMN_CSS

    rule = re.search(r'\[class\*="st-key-rv_open_"\] \{([^}]*)\}', COLUMN_CSS).group(1)
    assert "width: 100% !important" in rule and "height: 100% !important" in rule
