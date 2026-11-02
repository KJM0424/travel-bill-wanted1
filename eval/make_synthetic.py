"""평가용 샘플 영수증 이미지를 만든다. 정답은 spec에서 계산해 ground_truth.json에 넣는다.

사용법: python -m eval.make_synthetic --font /System/Library/Fonts/AppleSDGothicNeo.ttc
"""

import argparse
import hashlib
import json
from datetime import datetime, timedelta
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


# 줄 앞에 붙여 그리는 방식을 정한다. receipt_lines·booking_lines는 (왼쪽, 오른쪽) 글자 쌍을 돌려준다.
CENTER = "\x00c"
BIG = "\x00b"
RULE = "\x00-"
QTY = "\t"
WEEKDAYS = "월화수목금토일"
CARD_PREFIXES = ["5412", "4579", "9410", "3560"]


def vat_split(total: int) -> tuple[int, int]:
    """부가세 포함 금액을 공급가액과 부가세(10%)로 나눈다."""
    supply = round(total / 1.1)
    return supply, total - supply


def _seed(spec: dict) -> int:
    """같은 spec이면 늘 같은 카드번호·승인번호가 나오도록 id로 정한다."""
    return int(hashlib.sha256(spec["id"].encode()).hexdigest(), 16)


def masked_card(spec: dict) -> str:
    """실제 영수증처럼 가운데를 가린 카드번호. 전체 번호는 만들지 않는다."""
    seed = _seed(spec)
    return f"{CARD_PREFIXES[seed % 4]}-{seed // 7 % 100:02d}**-****-{seed // 11 % 10000:04d}"


def _approval(spec: dict) -> str:
    return f"{_seed(spec) // 13 % 100_000_000:08d}"


def _paid_text(spec: dict) -> str:
    """영수증마다 날짜 표기가 다르다. 정답(paid_at)은 같다."""
    when = datetime.fromisoformat(spec["paid_at"])
    style = spec.get("time_style", "dash")
    if style == "slash":
        return when.strftime("%Y/%m/%d %H:%M:") + f"{_seed(spec) % 60:02d}"
    if style == "short":
        return when.strftime("%y.%m.%d") + f"({WEEKDAYS[when.weekday()]}) " + when.strftime("%H:%M")
    return when.strftime("%Y-%m-%d %H:%M")


def _dot_date(value: str) -> str:
    day = datetime.fromisoformat(value)
    return day.strftime("%Y.%m.%d") + f" ({WEEKDAYS[day.weekday()]})"


def _item_rows(spec: dict) -> list[tuple[str, str]]:
    """같은 품목은 한 줄로 묶어 수량을 적는다."""
    grouped: dict[str, list[int]] = {}
    for item in spec["items"]:
        grouped.setdefault(item["name"], []).append(item["amount"])
    return [(f"{name}{QTY}{len(amounts)}", _won(sum(amounts))) for name, amounts in grouped.items()]


def _payment_rows(spec: dict) -> list[tuple[str, str]]:
    return [
        (f"[카드승인] {spec.get('card', '신한카드')}", ""),
        ("카드번호", masked_card(spec)),
        ("할부", "일시불"),
        ("승인번호", _approval(spec)),
    ]


def receipt_lines(spec: dict) -> list[tuple[str, str]]:
    seed = _seed(spec)
    total = expected_total(spec)
    supply, vat = vat_split(total)
    lines = [(CENTER + BIG + spec["merchant"], ""), (CENTER + spec["address"], "")]
    if spec.get("phone"):
        lines.append((CENTER + f"TEL {spec['phone']}", ""))
    lines += [
        (RULE, ""),
        ("[영수증]", f"POS {seed % 3 + 1:02d}  No.{seed // 17 % 9000 + 1000}"),
        (_paid_text(spec), ""),
        (RULE, ""),
        (f"품명{QTY}수량", "금액"),
        *_item_rows(spec),
        (RULE, ""),
        ("합계", _won(sum(i["amount"] for i in spec["items"]))),
    ]
    if spec.get("discount"):
        lines.append((spec.get("discount_label", "할인"), f"-{_won(spec['discount'])}"))
    lines += [
        (BIG + "결제금액", _won(total)),
        ("  과세물품가액", _won(supply)),
        ("  부가세", _won(vat)),
        (RULE, ""),
        *_payment_rows(spec),
        (RULE, ""),
        (CENTER + "이용해 주셔서 감사합니다", ""),
    ]
    return lines


def booking_lines(spec: dict) -> list[tuple[str, str]]:
    """예약 앱의 결제 완료 화면. 결제 시각 없이 결제일만 있다."""
    car = spec.get("booking_type") == "car"
    start_label, end_label = ("대여", "반납") if car else ("체크인", "체크아웃")
    start_time, end_time = ("09:00", "18:00") if car else ("15:00", "11:00")
    # 기간이 없으면 결제일에 시작해 다음 날 끝나는 1박으로 둔다.
    checkin = spec.get("checkin", spec["paid_at"][:10])
    checkout = (
        spec.get("checkout")
        or (datetime.fromisoformat(checkin) + timedelta(days=1)).date().isoformat()
    )
    lines = [
        (BIG + spec["merchant"], ""),
        (spec["address"], ""),
        (RULE, ""),
        ("예약번호", f"{spec['paid_at'].replace('-', '')}{_seed(spec) % 100000:05d}"),
        (start_label, f"{_dot_date(checkin)} {start_time}"),
        (end_label, f"{_dot_date(checkout)} {end_time}"),
        ("결제일", _dot_date(spec["paid_at"])),
        (RULE, ""),
        *[(name.replace(QTY, " x"), amount) for name, amount in _item_rows(spec)],
    ]
    if spec.get("discount"):
        lines.append((spec.get("discount_label", "쿠폰 할인"), f"-{_won(spec['discount'])}"))
    lines += [(RULE, ""), (BIG + "총 결제금액", _won(expected_total(spec))), *_payment_rows(spec)]
    return lines


def render_receipt(spec: dict, font_path: str) -> Image.Image:
    if spec.get("doc_type") == "booking_capture":
        return _render_booking(spec, font_path)
    return _draw(receipt_lines(spec), font_path)


def _won(amount: int) -> str:
    return f"{amount:,}원"


def _draw(lines: list[tuple[str, str]], font_path: str, top: int = MARGIN, img=None) -> Image.Image:
    """종이 영수증처럼 위에서 아래로 줄을 그린다."""
    big = ImageFont.truetype(font_path, 24)
    body = ImageFont.truetype(font_path, 17)
    if img is None:
        img = Image.new("RGB", (WIDTH, max(top + MARGIN + len(lines) * LINE_HEIGHT, 600)), "white")
    draw = ImageDraw.Draw(img)
    y = top
    for left, right in lines:
        if left == RULE:
            draw.line((MARGIN, y + 12, WIDTH - MARGIN, y + 12), fill=INK, width=1)
            y += LINE_HEIGHT - 6
            continue
        centered = left.startswith(CENTER)
        left = left.removeprefix(CENTER)
        font = big if left.startswith(BIG) else body
        left = left.removeprefix(BIG)
        if centered:
            draw.text((WIDTH // 2, y), left, fill=INK, font=font, anchor="ma")
        else:
            name, _, qty = left.partition(QTY)
            draw.text((MARGIN, y), name, fill=INK, font=font)
            if qty:
                draw.text((int(WIDTH * 0.62), y), qty, fill=INK, font=font, anchor="ra")
        if right:
            draw.text((WIDTH - MARGIN, y), right, fill=INK, font=font, anchor="ra")
        y += LINE_HEIGHT + (6 if font is big else 0)
    return img


def _render_booking(spec: dict, font_path: str) -> Image.Image:
    """예약 앱의 결제 완료 화면처럼 그린다. 상단 색 띠와 완료 문구를 둔다."""
    lines = booking_lines(spec)
    img = Image.new("RGB", (WIDTH, max(110 + MARGIN + len(lines) * LINE_HEIGHT, 640)), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, WIDTH, 76), fill=BOOKING_ACCENT)
    title = (
        "렌터카 예약이 완료되었어요" if spec.get("booking_type") == "car" else "예약이 확정되었어요"
    )
    draw.text((MARGIN, 24), title, fill="white", font=ImageFont.truetype(font_path, 24))
    return _draw(lines, font_path, top=100, img=img)


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
