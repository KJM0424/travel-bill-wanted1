import io
import json

from PIL import Image

from core.recognizer import MockRecognizer
from eval.run_eval import evaluate, save_results


def png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), color).save(buf, format="PNG")
    return buf.getvalue()


def entry(file, source="synthetic"):
    expected = {"doc_type": "receipt", "merchant_name": "x", "paid_at": None, "total_amount": 1}
    return {"file": file, "source": source, "kind": "cafe", "expected": expected}


def test_missing_image_becomes_error_row(tmp_path):
    (tmp_path / "synthetic").mkdir()
    (tmp_path / "synthetic" / "s01.png").write_bytes(png("white"))
    rows = evaluate(
        [entry("synthetic/s01.png"), entry("real/r01.jpg", "real")],
        MockRecognizer(),
        "v1",
        tmp_path,
    )
    assert [r["file"] for r in rows] == ["synthetic/s01.png", "real/r01.jpg"]
    assert rows[0]["error"] is None and "없습니다" in rows[1]["error"]
    assert rows[1]["core3"] is False


def test_evaluates_more_than_one_batch(tmp_path):
    (tmp_path / "synthetic").mkdir()
    entries = []
    for i in range(35):
        (tmp_path / "synthetic" / f"s{i}.png").write_bytes(png((i, 0, 0)))
        entries.append(entry(f"synthetic/s{i}.png"))
    assert len(evaluate(entries, MockRecognizer(), "v1", tmp_path)) == 35


def test_save_results_writes_json_and_csv(tmp_path):
    rows = evaluate([entry("real/r01.jpg", "real")], MockRecognizer(), "v1", tmp_path)
    raw_path, csv_path = save_results(rows, "v1", tmp_path / "results", "20261102-1200")
    assert (
        raw_path.name == "v1_20261102-1200.json" and csv_path.name == "v1_20261102-1200_summary.csv"
    )
    assert json.loads(raw_path.read_text(encoding="utf-8"))[0]["file"] == "real/r01.jpg"


def test_make_recognizer_supports_ollama(monkeypatch):
    from core.recognizer.ollama import OllamaRecognizer
    from eval.run_eval import _make_recognizer

    monkeypatch.setenv("OLLAMA_MODEL", "qwen3-vl:8b")
    recognizer = _make_recognizer("ollama")
    assert isinstance(recognizer, OllamaRecognizer) and recognizer.model == "qwen3-vl:8b"


def test_interval_recognizes_one_at_a_time_with_pauses(tmp_path):
    # 무료 등급은 분당 호출 수가 적어, 간격 없이 부르면 429로 실패했다.
    (tmp_path / "synthetic").mkdir()
    for i in range(3):
        (tmp_path / "synthetic" / f"s{i}.png").write_bytes(png((i, 0, 0)))
    pauses: list[float] = []
    rows = evaluate(
        [entry(f"synthetic/s{i}.png") for i in range(3)],
        MockRecognizer(),
        "v1",
        tmp_path,
        interval=12.0,
        sleep=pauses.append,
    )
    assert len(rows) == 3 and all(r["error"] is None for r in rows)
    assert pauses == [12.0, 12.0]


def test_select_entries_by_source():
    from eval.run_eval import select_entries

    entries = [entry("real/r01.jpg", "real"), entry("synthetic/s01.png")]
    assert [e["file"] for e in select_entries(entries, "synthetic", None)] == ["synthetic/s01.png"]
    assert len(select_entries(entries, None, 1)) == 1
