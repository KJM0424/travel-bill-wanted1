"""테스트셋으로 인식 정확도를 잰다.

사용법: python -m eval.run_eval --prompt v1 [--recognizer gemini|mock] [--limit N]
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from core.config import get_setting
from core.recognize_service import MAX_FILES, recognize_batch
from core.recognizer import MockRecognizer, RecognitionError, Recognizer
from eval.metrics import FIELDS, score_case, summarize

EVAL_DIR = Path(__file__).resolve().parent
GROUND_TRUTH_PATH = EVAL_DIR / "ground_truth.json"
IMAGES_DIR = EVAL_DIR / "images"
RESULTS_DIR = EVAL_DIR / "results"


def evaluate(
    entries: list[dict], recognizer: Recognizer, prompt_version: str, images_dir: Path
) -> list[dict]:
    """라벨 항목마다 인식하고 채점한 행을 입력 순서대로 돌려준다. 캐시는 쓰지 않는다."""
    outcomes = {}
    present = [e for e in entries if (images_dir / e["file"]).exists()]
    for start in range(0, len(present), MAX_FILES):
        chunk = present[start : start + MAX_FILES]
        files = [(e["file"], (images_dir / e["file"]).read_bytes()) for e in chunk]
        for outcome in recognize_batch(files, recognizer, prompt_version, cache={}):
            outcomes[outcome.filename] = outcome
    return [_score_row(entry, outcomes.get(entry["file"])) for entry in entries]


def _score_row(entry: dict, outcome) -> dict:
    receipt = outcome.receipt if outcome else None
    error = outcome.error if outcome else f"이미지 파일이 없습니다: {entry['file']}"
    return {
        "file": entry["file"],
        "source": entry["source"],
        "kind": entry["kind"],
        **score_case(entry["expected"], receipt),
        "seconds": outcome.elapsed_s if outcome else 0.0,
        "error": error,
        "expected": entry["expected"],
        "actual": receipt.model_dump() if receipt else None,
    }


def save_results(
    rows: list[dict], prompt_version: str, results_dir: Path, stamp: str
) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    raw_path = results_dir / f"{prompt_version}_{stamp}.json"
    csv_path = results_dir / f"{prompt_version}_{stamp}_summary.csv"
    raw_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summarize(rows).to_csv(csv_path, float_format="%.3f")
    return raw_path, csv_path


def mismatch_lines(rows: list[dict]) -> list[str]:
    """틀린 건을 '파일 | 필드 | 기대값 | 실제값'으로 나열한다. 실패 분석의 재료다."""
    lines = []
    for row in rows:
        if row["error"]:
            lines.append(f"{row['file']} | 오류 | - | {row['error']}")
            continue
        for field in FIELDS:
            if not row[field]:
                actual = row["actual"].get(field) if row["actual"] else None
                lines.append(f"{row['file']} | {field} | {row['expected'][field]} | {actual}")
    return lines


def _make_recognizer(kind: str) -> Recognizer:
    if kind == "mock":
        return MockRecognizer()
    from core.recognizer.gemini import DEFAULT_MODEL, GeminiRecognizer

    return GeminiRecognizer(
        get_setting("GEMINI_API_KEY") or "", model=get_setting("GEMINI_MODEL", DEFAULT_MODEL)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="영수증 인식 정확도 평가")
    parser.add_argument("--prompt", required=True, help="프롬프트 버전 (예: v1)")
    parser.add_argument("--recognizer", choices=["gemini", "mock"], default="gemini")
    parser.add_argument("--limit", type=int, help="앞에서부터 N건만 평가")
    args = parser.parse_args()

    try:
        recognizer = _make_recognizer(args.recognizer)
    except RecognitionError as e:
        raise SystemExit(str(e)) from None
    entries = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))[: args.limit]
    rows = evaluate(entries, recognizer, args.prompt, IMAGES_DIR)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    raw_path, csv_path = save_results(rows, args.prompt, RESULTS_DIR, stamp)

    print(summarize(rows).round(3).to_string())
    print("\n틀린 건 (파일 | 필드 | 기대값 | 실제값)")
    print("\n".join(mismatch_lines(rows)) or "없음")
    print(f"\n저장: {raw_path}\n저장: {csv_path}")


if __name__ == "__main__":
    main()
