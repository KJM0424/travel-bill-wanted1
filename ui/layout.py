"""모든 화면이 함께 쓰는 틀: 가운데 좁은 기둥, 상단 진행 표시, 하단 고정 버튼, 넘겨받은 안내."""

from collections.abc import Callable
from typing import Any

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from ui.state import START_STEP, STEPS, go_to, recognizer_name, session

# 휴대폰 한 손 화면 폭. 데스크톱에서도 이 폭으로 가운데에 둔다.
COLUMN_WIDTH = 480
# 테마 설정(.streamlit/config.toml)으로 못 하는 것만 CSS로 한다. 우리가 붙인 key 클래스만 건드린다.
# 색은 config.toml과 같은 값이다: 글자 #191F28, 보조 글자 #6B7684, 선 #E5E8EB, 강조 #17654C.
COLUMN_CSS = """
<style>
.st-key-page, .st-key-page_bottom { padding-left: 5px; padding-right: 5px; }
/* 한글은 낱말 중간에서 끊지 않는다("드려/요." 방지). 숫자는 자릿수를 맞춰 금액을 비교하기 쉽게 한다. */
.st-key-page p, .st-key-page li, .st-key-page h1, .st-key-page h2, .st-key-page h3 {
  word-break: keep-all;
}
.st-key-page { font-variant-numeric: tabular-nums; }
.st-key-page h1 { letter-spacing: -0.02em; line-height: 1.3; }
.st-key-page h2 { letter-spacing: -0.02em; }

/* 검토 화면: 은행 앱 거래 내역처럼 줄로 나눈 목록 */
[class*="st-key-row_"] { padding: 14px 0 12px; border-bottom: 1px solid #E5E8EB; }
[class*="st-key-row_"] p { margin-bottom: 0; }
[class*="st-key-ico_"] {
  flex: 0 0 40px; width: 40px; height: 40px; border-radius: 50%;
  background: #EEF5F1; color: #17654C; display: flex; align-items: center; justify-content: center;
}
[class*="st-key-ico_"] > div { width: auto !important; }
[class*="st-key-ico_"] p { margin: 0; line-height: 1; font-size: 20px; }
[class*="st-key-rt_"] { gap: 2px; }
[class*="st-key-rt_"] [data-testid="stCaptionContainer"] { margin: 0; }
/* 마크다운 기본 아래 여백(-1rem)이 다음 줄과 겹치게 해서 없앤다. */
[class*="st-key-row_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
/* 참석자 칩: 빠진 사람은 회색 취소선으로 바로 보이게 한다. */
[class*="st-key-part_"] button[aria-pressed="false"] p {
  color: #6B7684; text-decoration: line-through;
}
/* 줄 전체가 펼치기·접기 버튼이다. 투명 버튼을 줄 위에 덮고, 키보드로 왔을 때만 테두리를 보인다. */
[class*="st-key-rh_"] { position: relative; border-radius: 12px; }
[class*="st-key-rh_"]:hover { background: #F9FAFB; }
[class*="st-key-rv_open_"] { position: absolute !important; inset: 0; z-index: 2; margin: 0; }
[class*="st-key-rv_open_"] button {
  width: 100%; height: 100%; opacity: 0; cursor: pointer; border-radius: 12px;
}
[class*="st-key-rv_open_"] button:focus-visible {
  opacity: 1; color: transparent; background: transparent; outline: 2px solid #17654C;
}
/* 펼친 수정 칸: 입력칸(회색)과 구분되게 흰 바탕에 테두리 */
[class*="st-key-edit_"] {
  background: #FFFFFF; border: 1px solid #E5E8EB; border-radius: 14px; padding: 16px; margin-top: 8px;
}
[class*="st-key-day_head_"] { margin-top: 18px; }
[class*="st-key-day_head_"] p { color: #6B7684; font-weight: 600; font-size: 14px; }

/* 글씨: 본문 16px, 입력칸 이름 15px 굵게, 보조 설명 14px. 입력칸 글자는 16px라야 휴대폰에서 확대되지 않는다. */
.st-key-page [data-testid="stWidgetLabel"] p { font-size: 15px; font-weight: 600; color: #333D4B; }
.st-key-page [data-testid="stCaptionContainer"] { font-size: 14px; color: #6B7684; line-height: 1.5; }
.st-key-page input, .st-key-page textarea { font-size: 16px; }
.st-key-page h4 { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 4px; }

/* 설정 화면: 질문 하나에 카드 하나 */
[class*="st-key-sec_"] {
  border: 1px solid #E5E8EB; border-radius: 16px; padding: 18px 18px 20px; margin-bottom: 4px;
}
[class*="st-key-sec_"] h4 { padding-top: 0; }

/* 정산 화면: 영수증 한 장처럼 아래가 톱니 모양인 요약 */
.tv-slip {
  background: #F2F4F6; border-radius: 16px 16px 0 0; padding: 20px 20px 24px;
  position: relative; margin-bottom: 14px;
}
.tv-slip::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: -10px; height: 10px;
  background: radial-gradient(circle at 10px 0, #F2F4F6 7px, transparent 7.5px) 0 0 / 20px 10px repeat-x;
}
.tv-slip .tv-label { color: #191F28; font-weight: 600; font-size: 15px; margin: 0; }
.tv-slip .tv-label span { color: #6B7684; font-weight: 500; margin-left: 6px; }
.tv-slip .tv-total { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; margin: 2px 0 14px; }
.st-key-page .tv-slip dl {
  display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; margin: 0; padding: 0;
  font-size: 15px;
}
.st-key-page .tv-slip dt, .st-key-page .tv-slip dd { margin: 0; padding: 0; }
.tv-slip dt { color: #6B7684; }
.tv-slip dd { margin: 0; text-align: right; font-weight: 600; }

/* 여행 돌아보기 요약 카드: 정산 영수증과 구분되게 흰 바탕에 테두리만 둔다. */
.tv-story { border: 1px solid #E5E8EB; border-radius: 16px; padding: 18px 20px; margin-bottom: 12px; }
.tv-story .tv-story-head { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 12px; }
.st-key-page .tv-story dl {
  display: grid; grid-template-columns: auto 1fr; gap: 10px 12px; margin: 0 0 16px; padding: 0;
  font-size: 15px;
}
.st-key-page .tv-story dt, .st-key-page .tv-story dd { margin: 0; padding: 0; }
.tv-story dt { color: #6B7684; }
.tv-story dd { text-align: right; font-weight: 600; }
.tv-story dd small {
  display: block; color: #6B7684; font-weight: 500; font-size: 13px; word-break: keep-all;
}
.tv-story .tv-bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; gap: 2px; }
.tv-story .tv-legend {
  list-style: none; display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 10px 0 0; padding: 0;
  font-size: 13px; color: #4E5968;
}
.st-key-page .tv-story .tv-legend li { margin: 0; padding: 0; }
.tv-story .tv-legend i {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px;
}

/* 업로드 칸: Streamlit 기본 영어 문구("Upload", "200MB per file")를 한국어로 바꾸고 칸을 크게 한다. */
.st-key-upload_box [data-testid="stFileUploaderDropzone"] {
  flex-direction: column; justify-content: center; align-items: center; gap: 8px;
  min-height: 148px;
  background: #F7F8FA; border: 1.5px dashed #C9D1D9; border-radius: 16px;
}
.st-key-upload_box [data-testid="stFileUploaderDropzone"] button p { font-size: 0; }
.st-key-upload_box [data-testid="stFileUploaderDropzone"] button p::after {
  content: "사진 고르기"; font-size: 15px;
}
.st-key-upload_box [data-testid="stFileUploaderDropzoneInstructions"] { margin: 0; }
.st-key-upload_box [data-testid="stFileUploaderDropzoneInstructions"] span { font-size: 0; }
.st-key-upload_box [data-testid="stFileUploaderDropzoneInstructions"] span::after {
  content: "여러 장을 한 번에 골라도 돼요"; font-size: 14px; color: #6B7684;
}

/* 시작 화면: 세 단계 안내 */
.st-key-page ol.tv-steps {
  list-style: none; padding: 0; margin: 8px 0 0; display: grid; gap: 18px;
}
.st-key-page ol.tv-steps li {
  margin: 0; padding: 0; display: grid; grid-template-columns: 32px 1fr; gap: 14px;
}
.tv-steps .tv-num {
  width: 32px; height: 32px; border-radius: 50%; background: #EEF5F1; color: #17654C;
  display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 15px;
}
.tv-steps b { display: block; font-size: 17px; color: #191F28; }
.tv-steps span { color: #6B7684; font-size: 15px; }
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
    """앱 상단 막대: 왼쪽 이전 버튼, 오른쪽 '2/4' 단계 표시."""
    index = STEPS.index(step)
    previous = STEPS[index - 1] if index > 0 else START_STEP
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
    ):
        st.button(
            "이전",
            key="nav_back",
            type="tertiary",
            icon=":material/arrow_back_ios_new:",
            on_click=go_to,
            args=(previous,),
        )
        with st.container(horizontal=True, width="content", vertical_alignment="center"):
            demo_badge()
            st.caption(f"{index + 1}/{len(STEPS)}")


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
