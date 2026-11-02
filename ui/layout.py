"""모든 화면이 함께 쓰는 틀: 가운데 좁은 기둥, 상단 진행 표시, 하단 고정 버튼, 넘겨받은 안내."""

from collections.abc import Callable
from typing import Any

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from ui.state import START_STEP, STEP_LABELS, STEPS, go_to, recognizer_name, session

# 휴대폰 한 손 화면 폭. 데스크톱에서도 이 폭으로 가운데에 둔다.
COLUMN_WIDTH = 480
# 테마 설정으로 못 하는 두 가지만 CSS로 한다. 우리가 붙인 key 클래스만 건드린다.
# - 좌우 여백: Streamlit 기본 1rem(15px)에 5px를 더해 20px로 맞춘다.
# - 한글 줄바꿈: 낱말 중간에서 끊지 않는다("드려/요." 방지).
COLUMN_CSS = """
<style>
.st-key-page, .st-key-page_bottom { padding-left: 5px; padding-right: 5px; }
.st-key-page p, .st-key-page li, .st-key-page h1, .st-key-page h2, .st-key-page h3 {
  word-break: keep-all;
}
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
    """이전 버튼과 '2/4 영수증' 진행 표시."""
    index = STEPS.index(step)
    previous = STEPS[index - 1] if index > 0 else START_STEP
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
    ):
        st.button(
            "이전",
            key="nav_back",
            type="tertiary",
            icon=":material/arrow_back:",
            on_click=go_to,
            args=(previous,),
        )
        demo_badge()
    st.progress((index + 1) / len(STEPS), text=f"{index + 1}/{len(STEPS)} {STEP_LABELS[step]}")


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
