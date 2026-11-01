import pytest

from core import config


@pytest.fixture(autouse=True)
def isolate_from_local_files(monkeypatch, tmp_path):
    # 로컬 .streamlit/secrets.toml과 .env가 테스트 결과를 바꾸지 않게 한다.
    monkeypatch.setattr(config, "_read_streamlit_secret", lambda name: None)
    monkeypatch.setattr(config, "DOTENV_PATH", tmp_path / ".env")
