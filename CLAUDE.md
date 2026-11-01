# 여행 영수증 정산 앱

여행 영수증 이미지를 Gemini로 인식하고, 결제 건마다 결제자·참석자를 정해 정산하는 Streamlit 앱.

## 문서
- 설계 스펙: `docs/superpowers/specs/2026-11-01-trip-receipt-split-design.md`
- 구현 계획: `docs/superpowers/plans/2026-11-01-trip-receipt-split.md`
- AI 활용 기록: `docs/ai-log.md`

## 구조 규칙
- 화면은 `app.py`와 `ui/`, 계산과 외부 호출은 `core/`에 둔다.
- `core/`는 `streamlit`을 import하지 않는다. 예외는 `core/config.py`의 선택적 import뿐이다.
- 모든 모듈은 `core/schema.py`의 모델(`Receipt`, `Expense`, `Trip`)을 공통 계약으로 쓴다.

## 명령
- 셋업(작업 공간마다 한 번): `./scripts/setup_worktree.sh`
- 테스트: `.venv/bin/pytest`
- 린트: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- 실행: `.venv/bin/streamlit run app.py` (`RECOGNIZER=mock`이면 API 호출 없음)

## 지켜야 할 것
- API 키는 `.env`(로컬)와 `st.secrets`(배포)에만 둔다. 저장소에 커밋하지 않는다.
- 실물 영수증 사진(`eval/images/real/`)은 커밋하지 않는다.
- `prompts/`의 프롬프트를 바꾸면 무엇을 왜 바꿨는지 `docs/ai-log.md`에 기록한다.
- 새 기능은 실패하는 테스트를 먼저 쓴다.
