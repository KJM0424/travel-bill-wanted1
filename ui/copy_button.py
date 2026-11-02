"""송금 메시지 복사 버튼. st.code의 복사 아이콘은 마우스를 올려야 보여서 휴대폰에서는 찾기 어렵다."""

import streamlit as st

_HTML = '<button type="button" class="copy"></button>'

_CSS = """
.copy {
  width: 100%;
  min-height: 44px;
  font: inherit;
  font-weight: 600;
  color: var(--st-primary-color);
  background: var(--st-background-color);
  border: 1px solid var(--st-border-color);
  border-radius: var(--st-button-radius);
  cursor: pointer;
}
.copy:focus-visible { outline: 2px solid var(--st-primary-color); outline-offset: 2px; }
"""

_JS = """
export default function ({ data, parentElement }) {
  const button = parentElement.querySelector(".copy");
  if (!button) return;
  button.textContent = data.label;
  button.onclick = async () => {
    try {
      await navigator.clipboard.writeText(data.text);
      button.textContent = data.done;
    } catch (e) {
      button.textContent = data.failed;
    }
    setTimeout(() => { button.textContent = data.label; }, 1500);
  };
}
"""

_COPY_BUTTON = st.components.v2.component("travill_copy_button", html=_HTML, css=_CSS, js=_JS)


def copy_button(text: str, key: str, label: str = "메시지 복사") -> None:
    _COPY_BUTTON(
        data={
            "text": text,
            "label": label,
            "done": "복사했어요",
            "failed": "복사하지 못했어요. 글을 길게 눌러 복사해 주세요.",
        },
        key=key,
    )
