"""시연 영상 원본을 녹화한다. 앱을 정해진 순서대로 조작하고 장면마다 시작 시각을 남긴다.

앱 의존성과 섞지 않도록 Playwright는 따로 설치한 환경에서 돌린다.
    python -m venv videoenv && videoenv/bin/pip install playwright && videoenv/bin/python -m playwright install chromium
    RECOGNIZER=ollama streamlit run app.py --server.port 8630
    videoenv/bin/python scripts/record_demo.py --url http://localhost:8630 --out docs/demo/raw

결과: <out>/raw.webm(녹화), <out>/marks.json(장면 이름과 영상 안 시각, 초)
"""

import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RECEIPTS = [
    "s04",
    "s08",
    "s05",
    "s02",
    "s07",
    "s09",
]  # 1일차 국수·카페·마트, 2일차 호텔·생선구이, 3일차 우도
NOT_RECEIPT = ROOT / "docs/demo/sea.jpg"  # 영수증이 아닌 사진(바다 풍경 그림)
PDF = ROOT / "docs/demo/itinerary.pdf"
VIEWPORT = {"width": 430, "height": 932}

# 누르는 곳에 손가락 자국을 그린다. 녹화 영상에는 마우스 커서가 보이지 않는다.
TOUCH_JS = """
(() => {
  const dot = document.createElement('div');
  dot.id = 'tv-touch';
  dot.style.cssText = 'position:fixed;z-index:2147483647;width:44px;height:44px;margin:-22px 0 0 -22px;' +
    'border-radius:50%;background:rgba(23,101,76,.28);border:2px solid rgba(23,101,76,.7);' +
    'pointer-events:none;opacity:0;transform:scale(.6);transition:opacity .15s,transform .2s;left:-100px;top:-100px';
  const add = () => document.body && !document.getElementById('tv-touch') && document.body.appendChild(dot);
  document.addEventListener('DOMContentLoaded', add); add();
  window.tvTouch = (x, y) => {
    dot.style.left = x + 'px'; dot.style.top = y + 'px';
    dot.style.opacity = '1'; dot.style.transform = 'scale(1)';
    setTimeout(() => { dot.style.opacity = '0'; dot.style.transform = 'scale(.6)'; }, 450);
  };
})();
"""


class Recorder:
    def __init__(self, page: Page):
        self.page = page
        self.t0 = time.monotonic()
        self.marks: list[dict] = []

    def mark(self, scene: str) -> None:
        self.marks.append({"scene": scene, "t": round(time.monotonic() - self.t0, 2)})
        print(f"[{self.marks[-1]['t']:7.2f}] {scene}")

    def pause(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def tap(self, target: Locator, wait: float = 0.9) -> None:
        target.scroll_into_view_if_needed()
        box = target.bounding_box()
        if box:
            self.page.evaluate(
                "([x, y]) => window.tvTouch && window.tvTouch(x, y)",
                [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
            )
            self.pause(0.25)
        target.click()
        self.pause(wait)

    def type_into(self, target: Locator, text: str, enter: bool = True) -> None:
        self.tap(target, wait=0.2)
        target.press("Meta+A")
        target.press_sequentially(text, delay=60)
        if enter:
            target.press("Enter")
        self.pause(0.8)


def button(page: Page, name: str | re.Pattern) -> Locator:
    return page.get_by_role("button", name=name).first


def scroll_main(page: Page, dy: int) -> None:
    page.evaluate(
        f"document.querySelector('[data-testid=stMain]').scrollBy({{top:{dy},behavior:'smooth'}})"
    )
    page.wait_for_timeout(900)


def run(url: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=2,
            record_video_dir=str(out),
            # 녹화는 CSS 픽셀 크기로 된다. 더 크게 잡으면 남는 칸이 회색으로 채워진다.
            record_video_size=VIEWPORT,
            permissions=["clipboard-read", "clipboard-write"],
            locale="ko-KR",
        )
        context.add_init_script(TOUCH_JS)
        page = context.new_page()
        rec = Recorder(page)
        page.goto(url)
        expect(page.get_by_text("영수증 사진으로 끝내요")).to_be_visible(timeout=30000)
        rec.pause(1.5)

        rec.mark("시작")
        rec.pause(2.5)
        rec.tap(button(page, "정산 시작하기"), wait=1.5)

        rec.mark("여행 정보")
        rec.type_into(page.locator(".st-key-setup_name input"), "제주 2박 3일")
        # 날짜 칸은 연·월·일 칸(react-aria)이다. 연도 칸을 누르고 숫자만 치면 다음 칸으로 넘어간다.
        for key, digits in (("setup_start", "20261010"), ("setup_end", "20261012")):
            rec.tap(page.locator(f".st-key-{key} [data-type=year]"), wait=0.2)
            page.keyboard.type(digits, delay=90)
            page.keyboard.press("Tab")
            rec.pause(0.8)
        rec.type_into(page.locator(".st-key-setup_members input"), "재민, 수아, 민호")
        rec.pause(0.8)
        scroll_main(page, 520)
        # 위젯 key의 한글은 CSS 클래스에서 "--"로 바뀌어 사람마다 같은 클래스가 된다. 총무 칸이 맨 앞이다.
        rec.tap(page.get_by_role("combobox", name="은행").first, wait=0.6)
        page.keyboard.type("카카오", delay=80)
        rec.pause(0.5)
        # 그냥 Enter면 친 글자가 새 항목으로 들어간다. 목록의 "카카오뱅크"를 고른다.
        rec.tap(page.get_by_role("option", name="카카오뱅크").first, wait=0.6)
        rec.pause(0.8)
        rec.type_into(
            page.locator(".st-key-setup_pay_--_account_number input").first, "3333-01-1234567"
        )
        rec.type_into(page.locator(".st-key-setup_pay_--_account_holder input").first, "김재민")
        rec.pause(1.0)
        rec.tap(button(page, "다음"), wait=1.5)

        rec.mark("PDF 안내")
        uploader = page.locator(".st-key-upload_box input[type=file]")
        uploader.set_input_files(str(PDF))
        rec.pause(1.0)
        rec.tap(button(page, "영수증 읽기"), wait=2.0)
        expect(page.get_by_text("이미지 파일만 올릴 수 있어요")).to_be_visible(timeout=20000)
        rec.pause(3.0)

        rec.mark("영수증 올리기")
        files = [str(ROOT / f"eval/images/synthetic/{name}.png") for name in RECEIPTS] + [
            str(NOT_RECEIPT)
        ]
        uploader.set_input_files(files)
        rec.pause(1.5)
        rec.tap(button(page, "영수증 읽기"), wait=1.0)
        rec.mark("인식 중")
        expect(page.get_by_text(re.compile(r"결제 \d+건을 읽었어요"))).to_be_visible(timeout=900000)
        rec.mark("인식 끝")
        rec.pause(4.0)
        rec.tap(button(page, "다음"), wait=2.0)

        rec.mark("결제 내역")
        rec.pause(2.5)
        fish = button(page, re.compile("생선구이.*펼치기"))
        rec.tap(fish, wait=1.5)
        rec.mark("결제 고치기")
        rec.pause(1.5)
        # 저녁은 민호가 냈다: 결제한 사람이 여러 명인 여행
        rec.tap(page.get_by_role("combobox", name="결제한 사람").first, wait=0.6)
        rec.tap(page.get_by_role("option", name="민호").first, wait=1.5)
        rec.tap(button(page, re.compile("생선구이.*접기")), wait=1.2)

        rec.mark("빠진 사람 빼기")
        cafe = button(page, re.compile("인디고.*펼치기"))
        rec.tap(cafe, wait=1.5)
        rec.tap(
            page.locator('[class*="st-key-part_"]').get_by_role("button", name="민호").first,
            wait=1.5,
        )
        rec.tap(button(page, re.compile("인디고.*접기")), wait=1.5)
        rec.pause(1.0)

        rec.tap(button(page, "정산하기"), wait=2.5)
        rec.mark("보낼 돈")
        rec.pause(2.0)
        rec.tap(page.get_by_text("계좌 복사").first, wait=2.0)
        rec.pause(1.5)

        rec.mark("사람별 정산")
        rec.tap(page.get_by_role("radio", name="사람별 정산"), wait=3.0)

        rec.mark("여행 돌아보기")
        rec.tap(page.get_by_role("radio", name="여행 돌아보기"), wait=6.0)
        scroll_main(page, 560)
        rec.pause(1.5)
        replay = page.frame_locator("iframe").get_by_role("button", name=re.compile("다시 보기"))
        rec.mark("다시 보기")
        replay.click()
        rec.pause(14.0)
        rec.mark("끝")
        rec.pause(1.0)

        video = page.video
        context.close()
        browser.close()
        Path(video.path()).replace(out / "raw.webm")
    (out / "marks.json").write_text(
        json.dumps(rec.marks, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="시연 영상 원본 녹화")
    parser.add_argument("--url", default="http://localhost:8630")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/demo/raw")
    args = parser.parse_args()
    run(args.url, args.out)


if __name__ == "__main__":
    main()
