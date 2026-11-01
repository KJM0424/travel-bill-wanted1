import json
from pathlib import Path

import pytest
from PIL import Image

from eval.make_synthetic import apply_variant, expected_total, generate, render_receipt

MAC_KOREAN_FONT = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")

SPEC = {
    "id": "s01",
    "kind": "cafe",
    "merchant": "바람카페",
    "address": "제주특별자치도 제주시 애월읍 애월로 1",
    "paid_at": "2026-10-11T15:02",
    "items": [{"name": "아메리카노", "amount": 4500}, {"name": "카페라테", "amount": 5000}],
    "discount": 500,
    "variant": "clean",
}


@pytest.fixture
def korean_font() -> str:
    if not MAC_KOREAN_FONT.exists():
        pytest.skip("macOS 한글 폰트가 없습니다")
    return str(MAC_KOREAN_FONT)


def test_expected_amount_applies_discount():
    spec = {
        "items": [{"name": "a", "amount": 5000}, {"name": "b", "amount": 3000}],
        "discount": 1000,
    }
    assert expected_total(spec) == 7000


def test_render_produces_portrait_image(korean_font):
    img = render_receipt(SPEC, korean_font)
    assert img.height > img.width


def test_render_booking_capture(korean_font):
    spec = SPEC | {
        "id": "s02",
        "kind": "lodging",
        "doc_type": "booking_capture",
        "paid_at": "2026-10-10",
    }
    assert render_receipt(spec, korean_font).height > 0


@pytest.mark.parametrize("variant", ["clean", "blur", "rotate", "dark"])
def test_apply_variant_keeps_rgb_image(variant):
    img = Image.new("RGB", (100, 200), "white")
    out = apply_variant(img, variant)
    assert out.mode == "RGB" and out.width >= 100


def test_regenerate_keeps_real_entries(tmp_path, korean_font):
    gt = tmp_path / "gt.json"
    gt.write_text(
        json.dumps([{"file": "real/r01.jpg", "source": "real", "kind": "food", "expected": {}}])
    )
    generate([SPEC], korean_font, tmp_path / "img", gt)
    files = [e["file"] for e in json.loads(gt.read_text())]
    assert "real/r01.jpg" in files and "synthetic/s01.png" in files
    assert (tmp_path / "img" / "s01.png").exists()


def test_regenerate_replaces_old_synthetic_entries(tmp_path, korean_font):
    gt = tmp_path / "gt.json"
    old = {"file": "synthetic/s99.png", "source": "synthetic", "kind": "cafe", "expected": {}}
    gt.write_text(json.dumps([old]))
    generate([SPEC], korean_font, tmp_path / "img", gt)
    entries = json.loads(gt.read_text())
    assert [e["file"] for e in entries] == ["synthetic/s01.png"]
    assert entries[0]["expected"] == {
        "doc_type": "receipt",
        "merchant_name": "바람카페",
        "paid_at": "2026-10-11T15:02",
        "total_amount": 9000,
    }
