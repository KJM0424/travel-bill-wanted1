"""녹화 원본(raw.webm, marks.json)과 대본(docs/demo/script.md)으로 시연 영상을 만든다.

- 화면: 1920×1080. 왼쪽에 휴대폰 화면, 오른쪽에 장면 설명 카드, 아래에 자막
- 인식을 기다리는 구간만 빨리 감고, 배수를 카드에 적는다
- 음성: macOS `say -v Yuna`. 음성이 장면보다 길면 그 장면의 마지막 화면을 잠시 멈춰 맞춘다

이 ffmpeg에는 자막·글자 필터(libass, drawtext)가 없어, 글자는 Pillow로 그린 PNG를 겹친다.
    python scripts/make_demo_video.py --raw docs/demo/raw --out docs/demo/travill-demo.mp4
"""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs/demo/script.md"
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"  # 0 Regular, 2 Medium, 6 Bold
W, H = 1920, 1080
PHONE_H = 960
VIEWPORT_W, VIEWPORT_H = 430, 932  # scripts/record_demo.py의 VIEWPORT
BG = (243, 245, 244)
INK, SUB, PRIMARY, SOFT = (25, 31, 40), (91, 101, 114), (23, 101, 76), (231, 241, 236)
FAST_SCENE = "인식 중"
FAST_TARGET_S = 9.0
VOICE = ["say", "-v", "Yuna", "-r", "185"]
TAIL_S = 0.6  # 음성이 끝난 뒤 다음 장면까지 쉬는 시간


def font(size: int, weight: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size, index=weight)


def parse_script(path: Path) -> dict[str, dict]:
    """'## 장면 | 카드 제목 | 카드 설명' 다음 줄이 읽을 문장이다."""
    scenes = {}
    for block in re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.M)[1:]:
        head, *body = block.strip().splitlines()
        name, title, desc = (part.strip() for part in head.split("|"))
        scenes[name] = {
            "title": title,
            "desc": desc,
            "say": " ".join(b.strip() for b in body if b.strip()),
        }
    return scenes


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    """한국어는 낱말(공백) 단위로 줄을 바꾼다."""
    lines, line = [], ""
    for word in text.split(" "):
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return [*lines, line] if line else lines


def card_png(scene: dict, badge: str | None, out: Path) -> None:
    """오른쪽 설명 카드와 아래 자막을 한 장의 투명 PNG로 그린다."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x, y, cw = 820, 300, 960
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x, y, x + cw, y + 300], 32, fill=(16, 24, 32, 26))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    d.rounded_rectangle([x, y - 4, x + cw, y + 296], 32, fill=(255, 255, 255, 255))
    d.text((x + 56, y + 52), scene["title"], font=font(60, 6), fill=INK)
    for i, line in enumerate(wrap(d, scene["desc"], font(36, 2), cw - 112)):
        d.text((x + 56, y + 150 + i * 52), line, font=font(36, 2), fill=SUB)
    if badge:
        bw = d.textlength(badge, font=font(30, 6)) + 48
        d.rounded_rectangle([x, y - 84, x + bw, y - 28], 28, fill=SOFT + (255,))
        d.text((x + 24, y - 76), badge, font=font(30, 6), fill=PRIMARY)
    # 자막: 화면 아래 어두운 띠
    lines = wrap(d, scene["say"], font(34, 2), cw - 80)
    top = H - 96 - 50 * len(lines)
    d.rounded_rectangle([x, top - 24, x + cw, H - 72], 24, fill=(25, 31, 40, 225))
    for i, line in enumerate(lines):
        d.text((x + 40, top + i * 50), line, font=font(34, 2), fill=(255, 255, 255))
    im.save(out)


def frame_png(out: Path, phone_w: int) -> None:
    """바탕과 휴대폰 테두리, 왼쪽 위 이름표."""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im, "RGBA")
    px, py = 200, (H - PHONE_H) // 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [px - 14, py - 14, px + phone_w + 14, py + PHONE_H + 14], 52, fill=(16, 24, 32, 40)
    )
    im.paste(
        shadow.filter(ImageFilter.GaussianBlur(22)),
        (0, 12),
        shadow.filter(ImageFilter.GaussianBlur(22)),
    )
    d.rounded_rectangle(
        [px - 12, py - 12, px + phone_w + 12, py + PHONE_H + 12], 48, fill=(255, 255, 255)
    )
    d.text((820, 120), "Travill 시연", font=font(34, 6), fill=PRIMARY)
    d.text(
        (820, 168),
        "영수증 인식: 이 컴퓨터의 로컬 모델(Ollama) · 배포판은 Gemini API",
        font=font(26, 2),
        fill=SUB,
    )
    im.save(out)


def build(raw_dir: Path, out_path: Path) -> None:
    raw = raw_dir / "raw.webm"
    marks = json.loads((raw_dir / "marks.json").read_text(encoding="utf-8"))
    scenes = parse_script(SCRIPT)
    total_raw = duration(raw)
    work = Path(tempfile.mkdtemp(prefix="travill-demo-"))

    segments, t_out = [], 0.0
    for i, mark in enumerate(marks):
        start = mark["t"]
        end = marks[i + 1]["t"] if i + 1 < len(marks) else total_raw
        scene = scenes[mark["scene"]]
        speed = max(1.0, (end - start) / FAST_TARGET_S) if mark["scene"] == FAST_SCENE else 1.0
        voice = work / f"v{i:02d}.aiff"
        subprocess.run([*VOICE, "-o", str(voice), scene["say"]], check=True)
        spoken = duration(voice)
        length = (end - start) / speed
        hold = max(0.0, spoken + TAIL_S - length)
        badge = f"실제 {round(end - start)}초 → {speed:.0f}배 빨리 감기" if speed > 1 else None
        card = work / f"c{i:02d}.png"
        card_png(scene, badge, card)
        segments.append(
            {
                "start": start,
                "end": end,
                "speed": speed,
                "hold": hold,
                "voice": voice,
                "card": card,
                "at": t_out,
                "len": length + hold,
            }
        )
        t_out += length + hold

    frame = work / "frame.png"
    phone_w = round(PHONE_H * VIEWPORT_W / VIEWPORT_H / 2) * 2
    frame_png(frame, phone_w)

    parts = [f"[0:v]split={len(segments)}" + "".join(f"[s{i}]" for i in range(len(segments)))]
    for i, seg in enumerate(segments):
        parts.append(
            f"[s{i}]trim=start={seg['start']}:end={seg['end']},setpts=(PTS-STARTPTS)/{seg['speed']},"
            f"fps=30,tpad=stop_mode=clone:stop_duration={seg['hold']:.2f}[v{i}]"
        )
    parts.append(
        "".join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[cat]"
    )
    # Playwright는 CSS 픽셀(430×932)로 녹화한다. 녹화 칸이 더 크면 왼쪽 위에만 찍히므로 그 부분만 쓴다.
    parts.append(
        f"[cat]crop={VIEWPORT_W}:{VIEWPORT_H}:0:0,scale={phone_w}:{PHONE_H}:flags=lanczos[phone]"
    )
    parts.append(f"[1:v][phone]overlay=200:{(H - PHONE_H) // 2}[base0]")
    for i, seg in enumerate(segments):
        parts.append(
            f"[base{i}][{i + 2}:v]overlay=0:0:enable='between(t,{seg['at']:.2f},{seg['at'] + seg['len']:.2f})'"
            f"[base{i + 1}]"
        )
    voice_start = len(segments) + 2
    for i, seg in enumerate(segments):
        ms = int(seg["at"] * 1000)
        parts.append(f"[{voice_start + i}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    parts.append(
        "".join(f"[a{i}]" for i in range(len(segments)))
        + f"amix=inputs={len(segments)}:normalize=0[aud]"
    )

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-loop", "1", "-i", str(frame)]
    for seg in segments:
        cmd += ["-loop", "1", "-i", str(seg["card"])]
    for seg in segments:
        cmd += ["-i", str(seg["voice"])]
    cmd += [
        "-filter_complex",
        ";".join(parts),
        "-map",
        f"[base{len(segments)}]",
        "-map",
        "[aud]",
        "-t",
        f"{t_out:.2f}",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "20",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    print(f"{out_path} ({t_out:.1f}초)")
    for seg, mark in zip(segments, marks, strict=True):
        print(f"  {seg['at']:6.1f}s  {mark['scene']}  x{seg['speed']:.1f}  +{seg['hold']:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="시연 영상 편집")
    parser.add_argument("--raw", type=Path, default=ROOT / "docs/demo/raw")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/demo/travill-demo.mp4")
    args = parser.parse_args()
    build(args.raw, args.out)


if __name__ == "__main__":
    main()
