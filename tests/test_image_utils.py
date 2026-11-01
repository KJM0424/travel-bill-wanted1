import io

import pytest
from PIL import Image

from core.image_utils import UnsupportedImageError, image_hash, normalize_image

GPS_IFD_TAG = 0x8825
ORIENTATION_TAG = 0x0112


def make_png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg_with_exif_gps() -> bytes:
    exif = Image.Exif()
    exif[GPS_IFD_TAG] = {1: "N", 2: (33.0, 30.0, 0.0)}
    buf = io.BytesIO()
    Image.new("RGB", (100, 50), "white").save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def make_rotated_jpeg() -> bytes:
    """가로 200x100으로 저장됐지만 EXIF 회전값(6=90도)이 붙은 사진."""
    exif = Image.Exif()
    exif[ORIENTATION_TAG] = 6
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_normalize_shrinks_long_side():
    out = Image.open(io.BytesIO(normalize_image(make_png(3000, 1000))))
    assert max(out.size) == 1500 and out.format == "JPEG"


def test_normalize_keeps_small_image_size():
    assert Image.open(io.BytesIO(normalize_image(make_png(800, 600)))).size == (800, 600)


def test_normalize_strips_exif():
    out = Image.open(io.BytesIO(normalize_image(make_jpeg_with_exif_gps())))
    assert not out.getexif()


def test_normalize_applies_exif_rotation():
    out = Image.open(io.BytesIO(normalize_image(make_rotated_jpeg())))
    assert out.size == (100, 200)


def test_normalize_rejects_non_image():
    with pytest.raises(UnsupportedImageError):
        normalize_image(b"%PDF-1.4 not an image")


def test_image_hash_is_stable():
    data = make_png(10, 10)
    assert image_hash(data) == image_hash(data) and len(image_hash(data)) == 64
