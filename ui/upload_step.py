"""2단계: 영수증 이미지를 여러 장 올려 인식하고 결제 건으로 추가한다."""

from collections.abc import Callable

import streamlit as st

from core.expense_builder import build_expenses, sort_expenses
from core.recognize_service import MAX_FILES, recognize_batch
from core.recognizer import RecognitionError
from ui import state
from ui.layout import bottom_button

PROMPT_VERSION = "v1"
# 업로더에서 형식을 막으면 Streamlit 영어 툴팁만 보이므로, 받은 뒤 직접 걸러 한국어로 안내한다.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic")
NOT_IMAGE_NOTICE = "{name}: 이미지 파일만 올릴 수 있어요 (JPG·PNG·HEIC)"
DATA_NOTICE = (
    "사진은 Google Gemini API로 보내 내용을 읽어요. 카드번호와 이름은 가리고 올려 주세요. "
    "사진은 서버에 저장하지 않아요."
)
LOCAL_DATA_NOTICE = "사진은 이 컴퓨터의 AI 모델로 읽어요. 외부로 보내지 않아요."


def process_uploads(
    files: list[tuple[str, bytes]], on_progress: Callable[[int, int], None] | None = None
) -> None:
    """인식 결과를 기존 결제 건 뒤에 붙이고 시간순으로 정렬한다. 안내는 세션에 남긴다."""
    store = state.session()
    store["upload_notices"] = []
    store["upload_error"] = None
    store["upload_added"] = 0
    if len(files) > MAX_FILES:
        store["upload_notices"] = [
            f"한 번에 {MAX_FILES}장까지 올릴 수 있어요. 지금 {len(files)}장을 골랐어요."
        ]
        return
    skipped = [name for name, _ in files if not name.lower().endswith(IMAGE_EXTENSIONS)]
    files = [(name, raw) for name, raw in files if name.lower().endswith(IMAGE_EXTENSIONS)]
    store["upload_notices"] = [NOT_IMAGE_NOTICE.format(name=name) for name in skipped]
    if not files:
        return
    try:
        recognizer = state.get_recognizer()
    except RecognitionError as e:
        store["upload_error"] = f"{e} 영수증 내용은 직접 입력할 수 있어요."
        return

    trip = state.get_trip()
    cache = store.setdefault("recognition_cache", {})
    outcomes = recognize_batch(files, recognizer, PROMPT_VERSION, cache, on_progress=on_progress)
    # 기존 id를 넘겨야 나눠 올려도 위젯 key가 겹치지 않는다.
    expenses, notes = build_expenses(
        outcomes, trip, existing_ids={e.expense_id for e in trip.expenses}
    )
    state.set_trip(trip.model_copy(update={"expenses": sort_expenses([*trip.expenses, *expenses])}))
    store["upload_notices"] += notes
    store["upload_added"] = len(expenses)


def render_upload() -> None:
    st.header("영수증을 올려 주세요", anchor=False)
    st.caption(LOCAL_DATA_NOTICE if state.recognizer_name() == "ollama" else DATA_NOTICE)
    has_expenses = bool(state.get_trip().expenses)
    with st.form("upload_form", clear_on_submit=True, border=False):
        files = st.file_uploader(
            f"영수증·예약 캡처 사진 (JPG·PNG·HEIC, 한 번에 {MAX_FILES}장까지)",
            accept_multiple_files=True,
        )
        # 아직 결제 건이 없으면 '읽기'가 이 화면의 주요 버튼이다.
        submitted = st.form_submit_button(
            "영수증 읽기",
            type="secondary" if has_expenses else "primary",
            width="stretch",
            icon=":material/document_scanner:",
        )

    if submitted:
        if not files:
            st.warning("사진을 1장 이상 골라 주세요.")
        else:
            bar = st.progress(0.0, text="영수증을 읽고 있어요")

            def on_progress(done: int, total: int) -> None:
                # recognize_batch가 호출 스레드(메인 스레드)에서 부른다.
                bar.progress(done / total, text=f"영수증을 읽고 있어요 {done}/{total}")

            process_uploads([(f.name, f.getvalue()) for f in files], on_progress)
            bar.empty()
            st.rerun()

    _render_outcome()
    st.button(
        "영수증 없이 직접 입력할게요",
        key="upload_manual",
        type="tertiary",
        on_click=state.go_to,
        args=("검토",),
    )
    if state.get_trip().expenses:
        bottom_button("다음", key="upload_next", on_click=state.go_to, args=("검토",))


def _render_outcome() -> None:
    store = state.session()
    if store.get("upload_error"):
        st.error(store["upload_error"])
    notices = store.get("upload_notices", [])
    if len(notices) == 1:
        st.warning(notices[0])
    elif notices:
        # 파일마다 상자를 띄우면 화면이 안내로 덮이므로 한 상자에 모은다.
        st.warning("\n".join(f"- {n}" for n in notices))
    if store.get("upload_added"):
        st.success(f"결제 {store['upload_added']}건을 추가했어요. 다음 화면에서 확인해 주세요.")
