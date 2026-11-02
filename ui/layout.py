"""모든 화면이 함께 쓰는 틀: 가운데 좁은 기둥, 상단 진행 표시, 하단 고정 버튼, 넘겨받은 안내."""

from collections.abc import Callable
from typing import Any

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from ui.state import START_STEP, STEPS, go_to, recognizer_name, session

# 휴대폰 한 손 화면 폭. 데스크톱에서도 이 폭으로 가운데에 둔다.
COLUMN_WIDTH = 480
# 위쪽 바 양옆 폭. 같게 두어야 가운데 화면 이름이 정말 가운데에 온다.
APPBAR_SIDE = 104
STEP_TITLES = {
    "설정": "여행 정보",
    "업로드": "영수증 올리기",
    "검토": "결제 내역",
    "정산": "정산 결과",
}
# 테마 설정(.streamlit/config.toml)으로 못 하는 것만 CSS로 한다. 우리가 붙인 key 클래스만 건드린다.
# 색은 config.toml과 같은 값이다: 글자 #191F28, 보조 글자 #6B7684, 선 #E5E8EB, 강조 #17654C.
COLUMN_CSS = """
<style>
/* 색·그림자·여백 토큰. 색 값은 .streamlit/config.toml과 같다. 여백은 8px 단위(4px는 촘촘한 곳의 반 칸)다. */
:root {
  --tv-bg: #F3F5F4;          /* 페이지 바탕: 초록 기운이 살짝 도는 회색 */
  --tv-surface: #FFFFFF;     /* 카드 */
  --tv-fill: #F1F3F2;        /* 입력칸·옅은 채움 */
  --tv-line: #E9ECEB;        /* 카드 안 가는 구분선 */
  --tv-primary: #17654C;     /* 여권 초록 */
  --tv-primary-soft: #E7F1EC;
  --tv-text: #191F28;
  --tv-text-sub: #5B6572;    /* 바탕(#F3F5F4) 위에서도 4.5:1을 넘는 보조 글자 */
  --tv-text-weak: #8B95A1;
  --tv-radius: 16px;
  --tv-shadow: 0 1px 2px rgba(16, 24, 32, 0.04), 0 4px 16px rgba(16, 24, 32, 0.04);
  --tv-s1: 8px; --tv-s2: 16px; --tv-s3: 24px; --tv-s4: 32px;
}
/* Streamlit은 새로고침하면 입력한 정산이 사라진다. 휴대폰에서 당겨서 새로고침되지 않게 막는다. */
html, body { overscroll-behavior-y: none; }
/* 머리말 태그만 붙이는 컴포넌트(ui/pwa.py). 자리를 차지하지 않게 한다. */
.st-key-pwa_head { position: absolute; width: 0; height: 0; overflow: hidden; }
.st-key-page, .st-key-page_bottom { padding-left: 4px; padding-right: 4px; }
/* 한글은 낱말 중간에서 끊지 않는다("드려/요." 방지). 숫자는 자릿수를 맞춰 금액을 비교하기 쉽게 한다. */
.st-key-page p, .st-key-page li, .st-key-page h1, .st-key-page h2, .st-key-page h3 {
  word-break: keep-all;
}
.st-key-page { font-variant-numeric: tabular-nums; }
.st-key-page h1 { letter-spacing: -0.02em; line-height: 1.3; }
.st-key-page h2 { letter-spacing: -0.02em; }

/* 글씨: 본문 16px, 입력칸 이름 15px 굵게, 보조 설명 14px. 입력칸 글자는 16px라야 휴대폰에서 확대되지 않는다. */
.st-key-page [data-testid="stWidgetLabel"] p { font-size: 15px; font-weight: 600; color: #333D4B; }
.st-key-page [data-testid="stCaptionContainer"] {
  font-size: 14px; color: var(--tv-text-sub); line-height: 1.5;
}
.st-key-page input, .st-key-page textarea { font-size: 16px; }
.st-key-page h4 { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 4px; }

/* 위쪽 바: 뒤로 아이콘, 가운데 화면 이름, 아래 진행 막대 */
.st-key-appbar { min-height: 48px; }
.st-key-appbar_title p { text-align: center; font-size: 17px; margin: 0; }
/* Streamlit이 글자 칸 아래에 넣는 -16px 여백 때문에 이름·배지가 아이콘보다 내려가 보였다. */
.st-key-appbar [data-testid="stMarkdownContainer"],
.st-key-appbar [data-testid="stCaptionContainer"] { margin-bottom: 0 !important; }
.st-key-appbar p { margin: 0 !important; }
.st-key-nav_back button { min-width: 44px; min-height: 44px; padding: 0; justify-content: flex-start; }
.st-key-nav_back button p {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}
.tv-progress { display: flex; gap: 4px; margin: 0 0 8px; }
.tv-progress i { flex: 1; height: 3px; border-radius: 2px; background: #DDE2E0; }
.tv-progress i.on { background: var(--tv-primary); }

/* 누를 때마다 Streamlit이 화면을 흐리게 다시 그린다. 앱처럼 그대로 두고 바뀐 곳만 바뀌게 한다. */
[data-stale="true"] { opacity: 1 !important; transition: none !important; }

/* 터치 영역: 칩·글자 버튼·접는 칸도 44px 이상(Apple HIG). */
.st-key-page [data-testid="stButtonGroup"] button { min-height: 44px; padding: 0 16px; }

/* 칩·탭 색: 안 고른 것은 흰 바탕, 고른 것은 연한 초록 바탕에 초록 글자. 회색 바탕 위에서도 고른 상태가 분명하다. */
.st-key-page [data-testid="stButtonGroup"] button {
  background: var(--tv-surface); border-color: var(--tv-line); color: var(--tv-text);
}
.st-key-page [data-testid="stButtonGroup"] button[aria-pressed="true"],
.st-key-page [data-testid="stButtonGroup"] button[aria-checked="true"] {
  background: var(--tv-primary-soft); border-color: var(--tv-primary); color: var(--tv-primary);
}
.st-key-page [data-testid="stButtonGroup"] button[aria-pressed="true"] p,
.st-key-page [data-testid="stButtonGroup"] button[aria-checked="true"] p { font-weight: 700; }
.st-key-page [data-testid="stBaseButton-tertiary"] { min-height: 44px; }
.st-key-page [data-testid="stExpander"] summary { min-height: 44px; }

/* 누르는 반응: 버튼·칩은 살짝 눌리고, 결제 줄은 바탕이 잠깐 진해진다. 펼친 칸은 부드럽게 나타난다. */
.st-key-page button, .st-key-page_bottom button {
  transition: transform 0.08s ease, background-color 0.12s ease;
  -webkit-tap-highlight-color: transparent;
}
.st-key-page button:active, .st-key-page_bottom button:active { transform: scale(0.98); }
[class*="st-key-rh_"]:active { background: var(--tv-fill); }
[class*="st-key-edit_"] { animation: tv-in 0.18s ease-out; }
@keyframes tv-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

/* 불러오는 동안 보일 자리(스켈레톤). 스피너 대신 나올 내용의 모양을 미리 보여 준다. */
.tv-skel {
  border-radius: 12px;
  background: linear-gradient(90deg, #E9ECEB 0%, #F4F6F5 50%, #E9ECEB 100%) 0 0 / 200% 100%;
  animation: tv-shimmer 1.2s ease-in-out infinite;
}
.tv-skel-card { background: var(--tv-surface); border-radius: var(--tv-radius); box-shadow: var(--tv-shadow);
  padding: 24px 16px; display: grid; gap: 16px; margin-bottom: 16px; }
@keyframes tv-shimmer { from { background-position: 100% 0; } to { background-position: -100% 0; } }
@media (prefers-reduced-motion: reduce) {
  .st-key-page button, .st-key-page_bottom button { transition: none; }
  .st-key-page button:active, .st-key-page_bottom button:active { transform: none; }
  [class*="st-key-edit_"], .tv-skel { animation: none; }
}

/* 카드: 테두리 대신 흰 바탕과 아주 옅은 그림자로 바탕(--tv-bg)에서 띄운다. */
[class*="st-key-sec_"] {
  background: var(--tv-surface); border-radius: var(--tv-radius); box-shadow: var(--tv-shadow);
  padding: 24px 16px; margin-bottom: 8px;
}
[class*="st-key-sec_"] h4 { padding-top: 0; }
[class*="st-key-tr_"], [class*="st-key-pc_"], [class*="st-key-dg_"], .st-key-empty_state {
  background: var(--tv-surface); border-radius: var(--tv-radius); box-shadow: var(--tv-shadow);
  padding: 16px;
}
[class*="st-key-dg_"] { padding: 8px 16px; }
.st-key-page [data-testid="stExpander"] details {
  border: none; background: var(--tv-surface); border-radius: var(--tv-radius); box-shadow: var(--tv-shadow);
}
.st-key-empty_state { padding: 32px 24px; }
.st-key-empty_state p, .st-key-empty_state h3, .st-key-empty_state h4 { text-align: center; }
.st-key-empty_state h4 { margin: 0; }
/* 빈 화면 아이콘: 연한 초록 원 안에 크게 */
.st-key-empty_state h3 { display: flex; justify-content: center; padding: 0; }
.st-key-empty_state h3 span[role="img"] {
  font-size: 32px !important; width: 64px; height: 64px; border-radius: 50%;
  display: inline-flex !important; align-items: center; justify-content: center;
  background: var(--tv-primary-soft);
}

/* 아래 고정 버튼: 흰 바탕, 위로 옅은 그림자. 아이폰 아래 여백만큼 띄운다. */
[data-testid="stBottom"] > div { box-shadow: 0 -4px 16px rgba(16, 24, 32, 0.04); background: var(--tv-surface); }
[data-testid="stBottomBlockContainer"] {
  padding-top: 16px !important; padding-bottom: calc(16px + env(safe-area-inset-bottom)) !important;
}

/* 토스트: 화면 아래 어두운 알약 모양. 확인만 하면 되는 안내에 쓴다. */
[data-testid="stToast"] {
  background: #191F28; color: #FFFFFF; border-radius: 16px; box-shadow: var(--tv-shadow);
}
[data-testid="stToast"] p, [data-testid="stToast"] span { color: #FFFFFF; }

/* 검토 화면: 날짜마다 카드 하나, 그 안에 은행 앱 거래 내역처럼 줄로 나눈 목록 */
[class*="st-key-row_"] { padding: 16px 0; border-bottom: 1px solid var(--tv-line); }
[class*="st-key-row_"]:last-child { border-bottom: none; }
[class*="st-key-row_"] p { margin-bottom: 0; }
[class*="st-key-ico_"] {
  flex: 0 0 40px; width: 40px; height: 40px; border-radius: 50%;
  background: var(--tv-primary-soft); color: var(--tv-primary);
  display: flex; align-items: center; justify-content: center;
}
[class*="st-key-ico_"] > div { width: auto !important; }
[class*="st-key-ico_"] p { margin: 0; line-height: 1; font-size: 20px; }
[class*="st-key-rt_"] { gap: 0; }
[class*="st-key-rt_"] [data-testid="stCaptionContainer"] { margin: 0; }
/* 마크다운 기본 아래 여백(-1rem)이 다음 줄과 겹치게 해서 없앤다. */
[class*="st-key-row_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
/* 참석자 칩: 빠진 사람은 회색 취소선으로 바로 보이게 한다. */
[class*="st-key-part_"] button[aria-pressed="false"] p {
  color: var(--tv-text-weak); text-decoration: line-through;
}
/* 줄 전체가 펼치기·접기 버튼이다. 투명 버튼을 줄 위에 덮고, 키보드로 왔을 때만 테두리를 보인다. */
[class*="st-key-rh_"] { position: relative; border-radius: 12px; }
[class*="st-key-rh_"]:hover { background: #F8F9F9; }
/* Streamlit이 버튼 칸에 글자 너비를 직접 넣어서 inset만으로는 줄을 다 덮지 못한다. 너비·높이를 강제한다. */
[class*="st-key-rv_open_"] {
  position: absolute !important; inset: 0; z-index: 2; margin: 0;
  width: 100% !important; height: 100% !important;
}
[class*="st-key-rv_open_"] > div { width: 100% !important; height: 100% !important; }
[class*="st-key-rv_open_"] button {
  width: 100%; height: 100%; opacity: 0; cursor: pointer; border-radius: 12px;
}
[class*="st-key-rv_open_"] button:focus-visible {
  opacity: 1; color: transparent; background: transparent; outline: 2px solid var(--tv-primary);
}
/* 펼친 수정 칸: 같은 카드 안에서 가는 선으로만 나눈다. 입력칸은 옅은 회색이라 흰 바탕에서 잘 보인다. */
[class*="st-key-edit_"] { padding: 16px 0 0; margin-top: 8px; border-top: 1px dashed var(--tv-line); }
[class*="st-key-day_head_"] { margin-top: 8px; }
[class*="st-key-day_head_"] p { color: var(--tv-text-sub); font-weight: 600; font-size: 14px; }

/* 정산 화면: 영수증 한 장처럼 아래가 톱니 모양인 요약 */
.tv-slip {
  background: var(--tv-surface); border-radius: var(--tv-radius) var(--tv-radius) 0 0; padding: 24px;
  position: relative; margin-bottom: 24px; box-shadow: 0 1px 2px rgba(16, 24, 32, 0.04);
}
.tv-slip::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: -10px; height: 10px;
  background: radial-gradient(circle at 10px 0, var(--tv-surface) 7px, transparent 7.5px) 0 0 / 20px 10px repeat-x;
}
.tv-slip .tv-label { color: var(--tv-text); font-weight: 600; font-size: 15px; margin: 0; }
.tv-slip .tv-label span { color: var(--tv-text-sub); font-weight: 500; margin-left: 8px; }
.tv-slip .tv-total { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 16px; }
.st-key-page .tv-slip dl {
  display: grid; grid-template-columns: 1fr auto; gap: 8px 16px; margin: 0; padding: 0;
  font-size: 15px;
}
.st-key-page .tv-slip dt, .st-key-page .tv-slip dd { margin: 0; padding: 0; }
.tv-slip dt { color: var(--tv-text-sub); }
.tv-slip dd { margin: 0; text-align: right; font-weight: 600; }

/* 여행 돌아보기 요약 카드 */
.tv-story {
  background: var(--tv-surface); border-radius: var(--tv-radius); box-shadow: var(--tv-shadow);
  padding: 24px 16px; margin-bottom: 16px;
}
.tv-story .tv-story-head { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 16px; }
.st-key-page .tv-story dl {
  display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; margin: 0 0 16px; padding: 0;
  font-size: 15px;
}
.st-key-page .tv-story dt, .st-key-page .tv-story dd { margin: 0; padding: 0; }
.tv-story dt { color: var(--tv-text-sub); }
.tv-story dd { text-align: right; font-weight: 600; }
.tv-story dd small {
  display: block; color: var(--tv-text-sub); font-weight: 500; font-size: 13px; word-break: keep-all;
}
.tv-story .tv-bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; gap: 4px; }
.tv-story .tv-legend {
  list-style: none; display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 8px 0 0; padding: 0;
  font-size: 13px; color: #4E5968;
}
.st-key-page .tv-story .tv-legend li { margin: 0; padding: 0; }
.tv-story .tv-legend i {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px;
}

/* 업로드 칸: Streamlit 기본 영어 문구("Upload", "200MB per file")를 한국어로 바꾸고 칸을 크게 한다. */
.st-key-upload_box [data-testid="stFileUploaderDropzone"] {
  flex-direction: column; justify-content: center; align-items: center; gap: 8px;
  min-height: 148px;
  background: var(--tv-surface); border: 1.5px dashed #C3CCC8; border-radius: var(--tv-radius);
}
.st-key-upload_box [data-testid="stFileUploaderDropzone"] button p { font-size: 0; }
.st-key-upload_box [data-testid="stFileUploaderDropzone"] button p::after {
  content: "사진 고르기"; font-size: 15px;
}
.st-key-upload_box [data-testid="stFileUploaderDropzoneInstructions"] { margin: 0; }
.st-key-upload_box [data-testid="stFileUploaderDropzoneInstructions"] span { font-size: 0; }
.st-key-upload_box [data-testid="stFileUploaderDropzoneInstructions"] span::after {
  content: "여러 장을 한 번에 골라도 돼요"; font-size: 14px; color: var(--tv-text-sub);
}

/* 시작 화면: 네 단계 안내 */
.st-key-page ol.tv-steps {
  list-style: none; padding: 0; margin: 8px 0 0; display: grid; gap: 24px;
}
.st-key-page ol.tv-steps li {
  margin: 0; padding: 0; display: grid; grid-template-columns: 32px 1fr; gap: 16px;
}
.tv-steps .tv-num {
  width: 32px; height: 32px; border-radius: 50%; background: var(--tv-primary-soft);
  color: var(--tv-primary);
  display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 15px;
}
.tv-steps b { display: block; font-size: 17px; color: var(--tv-text); }
.tv-steps span { color: var(--tv-text-sub); font-size: 15px; }
</style>
"""


def column(parent: DeltaGenerator | None = None, key: str = "page") -> DeltaGenerator:
    """가운데 정렬한 최대 480px 기둥. 화면이 더 좁으면 화면 폭에 맞춰 줄어든다."""
    outer = (parent or st).container(horizontal_alignment="center")
    return outer.container(width=COLUMN_WIDTH, key=key)


def apply_column_css() -> None:
    st.html(COLUMN_CSS)


def demo_badge() -> None:
    """API를 부르지 않는 체험 모드일 때만 작은 배지를 보인다."""
    if recognizer_name() == "mock":
        st.markdown(":gray-badge[체험 모드]", width="content")


def step_header(step: str) -> None:
    """앱 상단 막대: 왼쪽 뒤로 버튼, 가운데 화면 이름, 오른쪽 '2/4'. 아래에 진행 막대."""
    index = STEPS.index(step)
    previous = STEPS[index - 1] if index > 0 else START_STEP
    with st.container(
        key="appbar",
        horizontal=True,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    ):
        with st.container(width=APPBAR_SIDE):
            # 글자는 CSS로 숨기고 아이콘만 보인다. 화면 읽기 프로그램은 "이전"으로 읽는다.
            st.button(
                "이전",
                key="nav_back",
                type="tertiary",
                icon=":material/arrow_back_ios_new:",
                on_click=go_to,
                args=(previous,),
            )
        with st.container(key="appbar_title"):
            st.markdown(f"**{STEP_TITLES[step]}**")
        with st.container(
            width=APPBAR_SIDE,
            horizontal=True,
            horizontal_alignment="right",
            vertical_alignment="center",
            gap="small",
        ):
            demo_badge()
            st.caption(f"{index + 1}/{len(STEPS)}")
    st.html(progress_html(index))


def progress_html(index: int) -> str:
    """단계 수만큼 칸을 나눈 얇은 막대. 지금 단계까지 칠한다."""
    cells = "".join('<i class="on"></i>' if i <= index else "<i></i>" for i in range(len(STEPS)))
    return f'<div class="tv-progress" aria-hidden="true">{cells}</div>'


def bottom() -> DeltaGenerator:
    """화면 아래에 붙는 영역. 화면마다 주요 버튼 하나를 여기에 둔다."""
    return column(st.bottom, key="page_bottom")


def bottom_button(
    label: str,
    key: str,
    on_click: Callable[..., Any] | None = None,
    args: tuple = (),
    icon: str | None = None,
) -> bool:
    return bottom().button(
        label, key=key, type="primary", width="stretch", icon=icon, on_click=on_click, args=args
    )


def flash(kind: str, message: str) -> None:
    """다음 화면에서 보여 줄 안내를 남긴다. kind는 info, success, warning 중 하나."""
    session().setdefault("flashes", []).append((kind, message))


def render_flashes() -> None:
    for kind, message in session().pop("flashes", []):
        getattr(st, kind)(message)
