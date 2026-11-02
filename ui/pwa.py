"""홈 화면에 추가했을 때 주소창 없이 앱처럼 열리게 하는 머리말 태그.

Streamlit은 <head>를 직접 고칠 수 없어서, 페이지 안에서 도는 작은 컴포넌트가 태그를 붙인다.
설정 파일과 아이콘은 static/에 있고 app/static/ 경로로 내려간다(.streamlit/config.toml의 enableStaticServing).
"""

import streamlit as st

HEAD_JS = """
export default function () {
  const head = document.head;
  const add = (tag, attrs) => {
    const key = attrs.rel ? `${tag}[rel="${attrs.rel}"]` : `${tag}[name="${attrs.name}"]`;
    if (head.querySelector(key)) return;
    const el = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    head.appendChild(el);
  };
  add("link", { rel: "manifest", href: "app/static/manifest.json" });
  add("link", { rel: "apple-touch-icon", href: "app/static/icon-192.png" });
  add("meta", { name: "theme-color", content: "#17654C" });
  add("meta", { name: "mobile-web-app-capable", content: "yes" });
  add("meta", { name: "apple-mobile-web-app-capable", content: "yes" });
  add("meta", { name: "apple-mobile-web-app-status-bar-style", content: "default" });
  add("meta", { name: "apple-mobile-web-app-title", content: "Travill" });
  // 아이폰 아래 여백(safe-area)을 CSS env()로 읽으려면 viewport-fit=cover가 있어야 한다.
  const viewport = head.querySelector('meta[name="viewport"]');
  if (viewport && !viewport.content.includes("viewport-fit")) {
    viewport.content += ", viewport-fit=cover";
  }
}
"""

_HEAD = st.components.v2.component("travill_pwa_head", html="<span></span>", js=HEAD_JS)


def inject_pwa_head() -> None:
    _HEAD(key="pwa_head")
