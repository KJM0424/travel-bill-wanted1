"""여행 영수증 정산 앱. 실행: streamlit run app.py"""

import hmac

import streamlit as st

from core.config import get_setting
from ui.branding import PAGE_TITLE
from ui.layout import apply_column_css, bottom_button, column, render_flashes, step_header
from ui.result_step import render_result
from ui.review_step import render_review
from ui.setup_step import render_setup
from ui.start_step import render_start
from ui.state import START_STEP, get_trip, go_to, init_widget, session
from ui.upload_step import render_upload

RENDERERS = {
    "설정": render_setup,
    "업로드": render_upload,
    "검토": render_review,
    "정산": render_result,
}


def check_password() -> bool:
    """APP_PASSWORD가 비어 있으면(로컬) 통과시킨다."""
    expected = get_setting("APP_PASSWORD")
    if not expected or session().get("authed"):
        return True
    entered = st.text_input("데모 비밀번호", type="password", key="password")
    if not entered:
        return False
    if hmac.compare_digest(entered.encode(), expected.encode()):
        session()["authed"] = True
        st.rerun()
    st.error("비밀번호가 맞지 않아요.")
    return False


def render_step(step: str) -> None:
    step_header(step)
    if step != "설정" and get_trip() is None:
        st.info("여행 정보를 먼저 알려 주세요.")
        bottom_button("여행 정보 입력하기", key="need_setup", on_click=go_to, args=("설정",))
        return
    render_flashes()
    RENDERERS[step]()


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon=":material/receipt_long:")
    apply_column_css()
    with column():
        if not check_password():
            return
        init_widget("step", START_STEP)
        step = session()["step"]
        if step == START_STEP:
            render_start()
        else:
            render_step(step)


main()
