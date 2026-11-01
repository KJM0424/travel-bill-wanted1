from core.config import get_setting


def test_get_setting_reads_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    assert get_setting("GEMINI_MODEL") == "test-model"


def test_get_setting_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert get_setting("NOPE_KEY", "fallback") == "fallback"
