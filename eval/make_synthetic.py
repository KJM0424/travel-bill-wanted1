"""평가용 샘플 영수증 이미지를 만든다. 정답은 spec에서 계산해 ground_truth.json에 넣는다.

사용법: python -m eval.make_synthetic --font /System/Library/Fonts/AppleSDGothicNeo.ttc
"""

import argparse
import json
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

EVAL_DIR = Path(__file__).resolve().parent
SPECS_PATH = EVAL_DIR / "synthetic_specs.json"
GROUND_TRUTH_PATH = EVAL_DIR / "ground_truth.json"
SYNTHETIC_DIR = EVAL_DIR / "images" / "synthetic"

WIDTH = 480
MARGIN = 28
LINE_HEIGHT = 30
INK = "black"
BOOKING_ACCENT = (36, 99, 235)

Variant = Literal["clean", "blur", "rotate", "dark"]


def expected_total(spec: dict) -> int:
    """실제 결제 금액 = 품목 합 − 할인·포인트."""
    return sum(item["amount"] for item in spec["items"]) - spec.get("discount", 0)


def expected_entry(spec: dict) -> dict:
    return {
        "file": f"synthetic/{spec['id']}.png",
        "source": "synthetic",
        "kind": spec["kind"],
        "expected": {
            "doc_type": spec.get("doc_type", "receipt"),
            "merchant_name": spec["merchant"],
            "paid_at": spec["paid_at"],
            "total_amount": expected_total(spec),
        },
    }


def render_receipt(spec: dict, font_path: str) -> Image.Image:
    if spec.get("doc_type") == "booking_capture":
        return _render_booking(spec, font_path)
    return _render_paper_receipt(spec, font_path)


def _won(amount: int) -> str:
    return f"{amount:,}원"


def _canvas(line_count: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    height = max(MARGIN * 2 + line_count * LINE_HEIGHT, int(WIDTH * 1.4))
    img = Image.new("RGB", (WIDTH, height), "white")
    return img, ImageDraw.Draw(img)


def _row(draw: ImageDraw.ImageDraw, y: int, left: str, right: str, font) -> None:
    draw.text((MARGIN, y), left, fill=INK, font=font)
    draw.text((WIDTH - MARGIN, y), right, fill=INK, font=font, anchor="ra")


def _render_paper_receipt(spec: dict, font_path: str) -> Image.Image:
    title = ImageFont.truetype(font_path, 26)
    body = ImageFont.truetype(font_path, 18)
    discount = spec.get("discount", 0)
    img, draw = _canvas(len(spec["items"]) + 12)
    y = MARGIN
    draw.text((WIDTH // 2, y), spec["merchant"], fill=INK, font=title, anchor="ma")
    y += LINE_HEIGHT + 10
    draw.text((MARGIN, y), spec["address"], fill=INK, font=body)
    y += LINE_HEIGHT
    draw.text((MARGIN, y), f"일시 {spec['paid_at'].replace('T', ' ')}", fill=INK, font=body)
    y += LINE_HEIGHT
    draw.text((MARGIN, y), "-" * 48, fill=INK, font=body)
    y += LINE_HEIGHT
    for item in spec["items"]:
        _row(draw, y, item["name"], _won(item["amount"]), body)
        y += LINE_HEIGHT
    draw.text((MARGIN, y), "-" * 48, fill=INK, font=body)
    y += LINE_HEIGHT
    _row(draw, y, "합계", _won(sum(i["amount"] for i in spec["items"])), body)
    y += LINE_HEIGHT
    if discount:
        _row(draw, y, spec.get("discount_label", "할인"), f"-{_won(discount)}", body)
        y += LINE_HEIGHT
    _row(draw, y, "결제금액", _won(expected_total(spec)), title)
    y += LINE_HEIGHT + 10
    draw.text((MARGIN, y), "카드 결제 / 일시불", fill=INK, font=body)
    return img


def _render_booking(spec: dict, font_path: str) -> Image.Image:
    """숙소 예약 앱의 결제 완료 화면처럼 그린다. 시간 없이 날짜만 있다."""
    title = ImageFont.truetype(font_path, 26)
    body = ImageFont.truetype(font_path, 18)
    img, draw = _canvas(len(spec["items"]) + 10)
    draw.rectangle((0, 0, WIDTH, 70), fill=BOOKING_ACCENT)
    draw.text((MARGIN, 22), "예약이 완료되었습니다", fill="white", font=title)
    y = 100
    draw.text((MARGIN, y), spec["merchant"], fill=INK, font=title)
    y += LINE_HEIGHT + 10
    draw.text((MARGIN, y), f"결제일 {spec['paid_at']}", fill=INK, font=body)
    y += LINE_HEIGHT * 2
    for item in spec["items"]:
        _row(draw, y, item["name"], _won(item["amount"]), body)
        y += LINE_HEIGHT
    if spec.get("discount"):
        _row(draw, y, spec.get("discount_label", "쿠폰 할인"), f"-{_won(spec['discount'])}", body)
        y += LINE_HEIGHT
    y += 10
    draw.line((MARGIN, y, WIDTH - MARGIN, y), fill=INK)
    y += 16
    _row(draw, y, "총 결제금액", _won(expected_total(spec)), title)
    return img


def apply_variant(img: Image.Image, variant: Variant) -> Image.Image:
    if variant == "blur":
        return img.filter(ImageFilter.GaussianBlur(1.5))
    if variant == "rotate":
        return img.rotate(7, expand=True, fillcolor="white")
    if variant == "dark":
        return ImageEnhance.Brightness(img).enhance(0.6)
    return img


def generate(specs: list[dict], font_path: str, images_dir: Path, ground_truth_path: Path) -> None:
    """이미지를 쓰고 ground_truth의 synthetic 항목을 spec 기준으로 바꾼다. 다른 항목은 그대로 둔다."""
    images_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        img = apply_variant(render_receipt(spec, font_path), spec.get("variant", "clean"))
        img.save(images_dir / f"{spec['id']}.png")
    existing = []
    if ground_truth_path.exists():
        existing = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    kept = [e for e in existing if e["source"] != "synthetic"]
    entries = kept + [expected_entry(spec) for spec in specs]
    ground_truth_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="평가용 샘플 영수증 생성")
    parser.add_argument("--font", required=True, help="한글 TTF/TTC 폰트 경로")
    parser.add_argument("--specs", type=Path, default=SPECS_PATH)
    args = parser.parse_args()
    specs = json.loads(args.specs.read_text(encoding="utf-8"))
    generate(specs, args.font, SYNTHETIC_DIR, GROUND_TRUTH_PATH)
    print(f"{len(specs)}장 생성: {SYNTHETIC_DIR}")


if __name__ == "__main__":
    main()
