"""시작 화면: 무엇을 하는 앱인지 네 단계로 보여 주고 '정산 시작하기' 버튼 하나를 둔다."""

import streamlit as st

from ui.branding import APP_NAME
from ui.layout import bottom_button, demo_badge, flash
from ui.setup_step import load_trip_file
from ui.state import go_to, session

STEPS_HTML = """
<ol class="tv-steps">
  <li><span class="tv-num">1</span><div><b>영수증을 한 번에 올려요</b>
    <span>종이 영수증도, 숙소 예약 캡처도 괜찮아요</span></div></li>
  <li><span class="tv-num">2</span><div><b>안 간 사람만 빼요</b>
    <span>결제를 눌러 빠진 친구 이름만 빼면 돼요</span></div></li>
  <li><span class="tv-num">3</span><div><b>송금 메시지를 보내요</b>
    <span>누가 누구에게 얼마를 보낼지 정리해 드려요</span></div></li>
  <li><span class="tv-num">4</span><div><b>여행을 돌아봐요</b>
    <span>다녀온 곳을 지도로 다시 보고, 어디에 얼마 썼는지 한눈에 봐요</span></div></li>
</ol>
"""


def render_start() -> None:
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
    ):
        # 로고 자리. 강조색은 이 이름과 주요 버튼에만 쓴다.
        st.markdown(f"#### :primary[{APP_NAME}]", anchors=False, width="content")
        demo_badge()
    st.space("medium")
    st.markdown("# 여행 정산,<br>영수증 사진으로 끝내요", unsafe_allow_html=True)
    st.space("small")
    st.html(STEPS_HTML)
    st.space("large")
    with st.expander("저장한 정산 이어서 하기", icon=":material/folder_open:"):
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
    flash("toast", "정산 파일을 불러왔어요.")
    go_to("검토")
    st.rerun()
