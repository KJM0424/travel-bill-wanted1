"""비용이 드는 AI 인식만 비밀번호로 막는다. 예시 여행 둘러보기와 정산 파일 불러오기는 누구나 쓴다."""

import hmac

import streamlit as st

from core.config import get_setting
from ui.state import session

PASSWORD_LABEL = "데모 비밀번호"
PASSWORD_NEEDED = "AI로 영수증을 읽으려면 비밀번호가 필요해요."


def ai_unlocked() -> bool:
    """APP_PASSWORD가 비어 있으면(로컬) 늘 열려 있다."""
    return not get_setting("APP_PASSWORD") or bool(session().get("authed"))


def render_password_gate() -> bool:
    """열려 있으면 True. 아니면 비밀번호 칸을 그리고 False."""
    if ai_unlocked():
        return True
    st.caption(PASSWORD_NEEDED)
    entered = st.text_input(PASSWORD_LABEL, type="password", key="password")
    if entered:
        expected = get_setting("APP_PASSWORD") or ""
        if hmac.compare_digest(entered.encode(), expected.encode()):
            session()["authed"] = True
            st.rerun()
        st.error("비밀번호가 맞지 않아요.")
    return False
