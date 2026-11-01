import pytest

from core import config
from core.config import get_setting


@pytest.fixture(autouse=True)
def isolate_from_local_files(monkeypatch, tmp_path):
    # 로컬 .streamlit/secrets.toml과 .env가 테스트 결과를 바꾸지 않게 한다.
    monkeypatch.setattr(config, "_read_streamlit_secret", lambda name: None)
    monkeypatch.setattr(config, "DOTENV_PATH", tmp_path / ".env")


def test_get_setting_reads_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    assert get_setting("GEMINI_MODEL") == "test-model"


def test_get_setting_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert get_setting("NOPE_KEY", "fallback") == "fallback"


def test_get_setting_reads_dotenv_when_env_was_blanked(monkeypatch, tmp_path):
    # Streamlit은 secrets.toml의 빈 값으로 os.environ을 덮어쓴다. 그래도 .env 값을 찾아야 한다.
    (tmp_path / ".env").write_text("GEMINI_API_KEY=real-key\n")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert get_setting("GEMINI_API_KEY") == "real-key"
