"""설정 값 조회: 배포는 st.secrets, 로컬은 .env(환경변수)."""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"

load_dotenv(DOTENV_PATH)


def _read_streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001
        # streamlit이 없거나 secrets.toml이 없으면 종류가 다른 예외가 난다.
        return None
    return str(value) if value else None


def _read_dotenv(name: str) -> str | None:
    # Streamlit은 secrets.toml의 값(빈 문자열 포함)으로 os.environ을 덮어쓰므로 .env를 직접 다시 읽는다.
    if not DOTENV_PATH.exists():
        return None
    return dotenv_values(DOTENV_PATH).get(name) or None


def get_setting(name: str, default: str | None = None) -> str | None:
    """st.secrets → 환경변수 → .env 파일 → default 순서로 찾는다. 빈 값은 없는 것으로 본다."""
    return (
        _read_streamlit_secret(name) or os.environ.get(name) or _read_dotenv(name) or default
    )
