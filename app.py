"""여행 영수증 정산 앱. 실행: streamlit run app.py"""

import hmac

import streamlit as st

from core.config import get_setting
from ui.result_step import render_result
from ui.review_step import render_review
from ui.setup_step import render_setup
from ui.state import STEPS, get_trip, recognizer_name, session
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
    st.error("비밀번호가 맞지 않습니다.")
    return False


def main() -> None:
    st.set_page_config(page_title="여행 영수증 정산", page_icon="🧾")
    st.title("🧾 여행 영수증 정산")
    if not check_password():
        return

    with st.sidebar:
        st.radio("단계", STEPS, key="step")
        mode = recognizer_name()
        st.caption(f"인식기: {mode}" + (" (API 호출 없음)" if mode == "mock" else ""))

    step = session()["step"]
    if step != "설정" and get_trip() is None:
        st.info("먼저 여행 설정을 저장하세요.")
        return
    RENDERERS[step]()


main()
