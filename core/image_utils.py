"""업로드 이미지 정규화: 회전 보정, EXIF 제거, 긴 변 축소."""

import hashlib
import io

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

pillow_heif.register_heif_opener()

MAX_LONG_SIDE = 1500
JPEG_QUALITY = 85


class UnsupportedImageError(ValueError):
    """이미지로 열 수 없는 파일."""


def image_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize_image(raw: bytes) -> bytes:
    """AI로 보내기 전에 JPEG로 바꾼다. EXIF(위치 등)는 저장하지 않는다."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except UnidentifiedImageError as e:
        raise UnsupportedImageError("이미지 파일이 아닙니다") from e
    img.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
