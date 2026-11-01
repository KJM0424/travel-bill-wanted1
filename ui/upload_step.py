"""2단계: 영수증 이미지를 여러 장 올려 인식하고 결제 건으로 추가한다."""

from collections.abc import Callable

import streamlit as st

from core.expense_builder import build_expenses, sort_expenses
from core.recognize_service import MAX_FILES, recognize_batch
from core.recognizer import RecognitionError
from ui import state

PROMPT_VERSION = "v1"
DATA_NOTICE = (
    "이미지는 Google Gemini API로 전송됩니다. 카드번호·이름은 가리고 올려 주세요. "
    "올린 이미지는 서버에 저장하지 않습니다."
)


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
            f"한 번에 최대 {MAX_FILES}장까지 올릴 수 있습니다. {len(files)}장을 골랐습니다."
        ]
        return
    try:
        recognizer = state.get_recognizer()
    except RecognitionError as e:
        store["upload_error"] = f"{e} 영수증 내용은 수동으로 추가할 수 있습니다."
        return

    trip = state.get_trip()
    cache = store.setdefault("recognition_cache", {})
    outcomes = recognize_batch(files, recognizer, PROMPT_VERSION, cache, on_progress=on_progress)
    # 기존 id를 넘겨야 나눠 올려도 위젯 key가 겹치지 않는다.
    expenses, notes = build_expenses(
        outcomes, trip, existing_ids={e.expense_id for e in trip.expenses}
    )
    state.set_trip(trip.model_copy(update={"expenses": sort_expenses([*trip.expenses, *expenses])}))
    store["upload_notices"] = notes
    store["upload_added"] = len(expenses)


def render_upload() -> None:
    st.header("2. 영수증 올리기")
    st.info(DATA_NOTICE)
    with st.form("upload_form", clear_on_submit=True):
        files = st.file_uploader(
            f"영수증·예약 캡처 이미지 (한 번에 최대 {MAX_FILES}장)",
            type=["jpg", "jpeg", "png", "heic"],
            accept_multiple_files=True,
        )
        submitted = st.form_submit_button("인식 시작", type="primary")

    if submitted:
        if not files:
            st.warning("이미지를 1장 이상 고르세요.")
        else:
            bar = st.progress(0.0, text="인식 중…")

            def on_progress(done: int, total: int) -> None:
                # recognize_batch가 호출 스레드(메인 스레드)에서 부른다.
                bar.progress(done / total, text=f"인식 중… {done}/{total}")

            process_uploads([(f.name, f.getvalue()) for f in files], on_progress)
            bar.empty()

    _render_outcome()
    st.button(
        "영수증 없는 지출은 수동으로 추가하기 →",
        key="upload_manual",
        on_click=state.go_to,
        args=("검토",),
    )


def _render_outcome() -> None:
    store = state.session()
    if store.get("upload_error"):
        st.error(store["upload_error"])
    for notice in store.get("upload_notices", []):
        st.warning(notice)
    if store.get("upload_added"):
        st.success(f"결제 건 {store['upload_added']}개를 추가했습니다. 검토 단계에서 확인하세요.")
        st.button("다음: 검토 →", key="upload_next", on_click=state.go_to, args=("검토",))
