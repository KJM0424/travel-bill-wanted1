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
