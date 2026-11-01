"""설정 값 조회: 배포는 st.secrets, 로컬은 .env(환경변수)."""

import os

from dotenv import load_dotenv

load_dotenv()


def _read_streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001
        # streamlit이 없거나 secrets.toml이 없으면 종류가 다른 예외가 난다.
        return None
    return str(value) if value else None


def get_setting(name: str, default: str | None = None) -> str | None:
    """st.secrets → 환경변수 → default 순서로 값을 찾는다. 빈 값은 없는 것으로 본다."""
    return _read_streamlit_secret(name) or os.environ.get(name) or default
