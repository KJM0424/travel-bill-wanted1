import pytest
from pydantic import ValidationError

from core.recognizer import MockRecognizer, RecognitionError
from core.schema import FUND_WALLET, Trip
from tests.ui_helpers import exp, trip_with
from ui.state import (
    add_members_to_expenses,
    get_recognizer,
    sync_members,
    validation_messages,
)


# Review Focus 2
def test_sync_members_removes_dropped_member_everywhere():
    t = trip_with([exp(9000, "C", ["A", "B", "C"])])
    t2 = sync_members(t, ["A", "B"], leader="A")
    assert t2.members == ["A", "B"]
    assert t2.expenses[0].participants == ["A", "B"]
    assert t2.expenses[0].payer == "A"


def test_sync_members_keeps_fund_wallet_payer():
    t = trip_with([exp(9000, FUND_WALLET, ["A", "B", "C"])], mode="fund", fee=10000)
    assert sync_members(t, ["A", "B"], leader="A").expenses[0].payer == FUND_WALLET


def test_sync_members_does_not_share_lists_with_original():
    t = trip_with([exp(9000, "C", ["A", "B", "C"])])
    sync_members(t, ["A", "B"], leader="A")
    assert t.expenses[0].participants == ["A", "B", "C"]


def test_sync_members_runs_trip_validation():
    t = trip_with([])
    with pytest.raises(ValidationError):
        sync_members(t, ["A", "A"], leader="A")


def test_sync_members_drops_payout_of_removed_member():
    t = Trip.model_validate({**trip_with([]).model_dump(), "payout": {"C": {"bank_account": "1"}}})
    assert "C" not in sync_members(t, ["A", "B"], leader="A").payout


def test_validation_messages_strip_pydantic_prefix():
    with pytest.raises(ValidationError) as info:
        sync_members(trip_with([]), ["A", "A"], leader="A")
    assert validation_messages(info.value) == ["참석자 이름이 중복돼요: A"]


def test_validation_messages_hide_english_type_errors():
    with pytest.raises(ValidationError) as info:
        Trip.model_validate({"name": 1})
    messages = validation_messages(info.value)
    assert messages and all("Input should" not in m and "Field required" not in m for m in messages)


def test_get_recognizer_mock(monkeypatch):
    monkeypatch.setenv("RECOGNIZER", "mock")
    assert isinstance(get_recognizer(), MockRecognizer)


def test_get_recognizer_gemini_without_key_raises(monkeypatch):
    monkeypatch.setenv("RECOGNIZER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RecognitionError, match="API 키"):
        get_recognizer()


def test_get_recognizer_ollama_uses_settings(monkeypatch):
    from core.recognizer.ollama import OllamaRecognizer

    monkeypatch.setenv("RECOGNIZER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3-vl:8b")
    monkeypatch.setenv("OLLAMA_HOST", "http://pc.local:11434")
    recognizer = get_recognizer()
    assert isinstance(recognizer, OllamaRecognizer)
    assert recognizer.model == "qwen3-vl:8b" and recognizer.host == "http://pc.local:11434"


def test_add_members_to_expenses_checks_new_member_everywhere():
    t = trip_with([exp(9000, "A", ["A", "B"])], members=["A", "B"])
    t = sync_members(t, ["A", "B", "C"], leader="A")
    t2 = add_members_to_expenses(t, ["C"])
    assert t2.expenses[0].participants == ["A", "B", "C"]
    assert t.expenses[0].participants == ["A", "B"]
