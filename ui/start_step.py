"""시작 화면: 서비스 소개와 '정산 시작하기' 버튼 하나. 저장한 정산 파일 불러오기는 보조로 둔다."""

import streamlit as st

from ui.branding import APP_NAME, TAGLINE
from ui.layout import bottom_button, demo_badge, flash
from ui.setup_step import load_trip_file
from ui.state import go_to, session


def render_start() -> None:
    st.space("large")
    # 로고 자리. 강조색은 이 이름과 주요 버튼에만 쓴다.
    st.title(f":primary[{APP_NAME}]", anchor=False)
    st.markdown(f"### {TAGLINE}", anchors=False)
    st.caption("영수증 사진을 올리면 누가 누구에게 얼마를 보내면 되는지 정리해 드려요.")
    demo_badge()
    st.space("medium")
    with st.expander("저장한 정산 파일 불러오기", icon=":material/folder_open:"):
        _render_import()
    bottom_button("정산 시작하기", key="start_begin", on_click=go_to, args=("설정",))


def _render_import() -> None:
    uploaded = st.file_uploader(
        "정산 단계에서 저장한 파일(JSON)",
        type=["json"],
        key="import_file",
    )
    # 업로더는 파일을 계속 들고 있으므로 같은 파일을 매번 다시 불러오지 않게 한다.
    if uploaded is None or session().get("imported_file_id") == uploaded.file_id:
        return
    session()["imported_file_id"] = uploaded.file_id
    error = load_trip_file(uploaded.getvalue())
    if error:
        st.error(error)
        return
    flash("success", "정산 파일을 불러왔어요. 이어서 확인해 보세요.")
    go_to("검토")
    st.rerun()
