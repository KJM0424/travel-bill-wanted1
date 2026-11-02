# 여행 영수증 정산

여행 영수증 사진을 여러 장 올리면 Gemini가 금액·일시·상호를 읽고, 결제 건마다 결제자와 참석자를 정해 사람별 정산액과 송금 메시지를 만드는 Streamlit 앱이다.

## 흐름
1. **설정**: 참석자, 총무, 정산 방식(선결제형 / 회비형 + 1인 회비), 총무 계좌(은행·계좌번호·예금주), 다른 사람 계좌와 송금 링크. 저장한 결과 JSON은 시작 화면에서 다시 불러온다.
2. **업로드**: 영수증·예약 캡처를 한 번에 최대 30장 올린다. 3장씩 병렬로 인식하고 시간순으로 정렬한다.
3. **검토**: 결제 건마다 상호·일시·주소·금액을 고치고, 결제자를 고르고, 빠진 참석자를 해제한다. 중복 의심 건을 경고하고, 영수증 없는 지출을 수동으로 추가한다.
4. **정산**: 사람별 "낸 돈 / 부담액 / 차액" 표, 송금마다 "메시지 복사"와 "계좌 복사"(은행과 계좌번호만, 은행 앱에 붙여 넣기용), 결과 JSON 내려받기. 결제 건마다 결제자가 달라도 받을 사람이 여러 명인 송금으로 나눈다.
5. **여행 돌아보기**(정산 화면 아래): 여행 요약(이동 거리, 가장 많이 쓴 날, 분류별 비율), 날짜별 색으로 그린 경로 지도와 날짜 필터, 자동차가 결제 순서대로 곡선 경로를 따라 달리는 "여행 다시 보기", 날짜별 동선. 이동 거리는 들른 곳 사이 직선거리의 합이라 실제 도로 거리보다 짧다.

## 로컬 실행
```bash
git clone git@github.com:KJM0424/travel-bill-wanted1.git
cd travel-bill-wanted1
./scripts/setup_worktree.sh        # .venv 생성, 패키지 설치, .env 준비
# .env에 키를 채운다 (아래 "설정 값" 참고)
.venv/bin/streamlit run app.py
```

API 호출 없이 화면만 확인하려면 mock 모드로 실행한다. 미리 저장한 인식 결과(`tests/fixtures/receipts/`)를 돌려준다.
```bash
RECOGNIZER=mock .venv/bin/streamlit run app.py
```

## 설정 값
로컬은 `.env`, 배포는 Streamlit Secrets에서 읽는다(`core/config.py`). 빈 값은 없는 것으로 본다.

| 이름 | 설명 |
|---|---|
| `GEMINI_API_KEY` | Gemini API 키. [Google AI Studio](https://aistudio.google.com/apikey)에서 발급한다 |
| `GEMINI_MODEL` | 비우면 `gemini-3.5-flash` |
| `RECOGNIZER` | `gemini`, `ollama`(이 컴퓨터의 로컬 모델, 로컬 전용), `mock`. 비우면 `gemini` |
| `OLLAMA_MODEL` | `RECOGNIZER=ollama`일 때 모델. 비우면 `qwen3-vl:8b-instruct` |
| `OLLAMA_HOST` | Ollama 서버 주소. 비우면 `http://localhost:11434` |
| `APP_PASSWORD` | 데모 비밀번호. 비우면 비밀번호 화면을 건너뛴다 |
| `KAKAO_REST_API_KEY` | 경로 지도용. [카카오 개발자](https://developers.kakao.com/)에서 발급하고, 앱 설정에서 카카오맵(지도·로컬) 사용을 켠다. 없으면 지도 대신 안내만 나온다 |

`.env`와 `.streamlit/secrets.toml`은 커밋하지 않는다(`.gitignore`에 있음).

## 테스트·평가
```bash
.venv/bin/pytest                                              # 단위 테스트 + 화면 테스트(AppTest)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/python -m eval.run_eval --prompt v1                 # 인식 정확도 (Gemini 키 필요)
.venv/bin/python -m eval.run_eval --prompt v1 --recognizer ollama   # 로컬 모델 (Ollama 필요)
.venv/bin/python -m eval.run_eval --prompt v1 --recognizer mock
```

### 로컬 모델(Ollama)
Gemini 대신 이 컴퓨터에서 도는 비전 모델로 인식한다. 호출 한도와 비용이 없고 사진이 외부로 나가지 않는다. Streamlit Cloud에는 GPU가 없어 배포판에서는 쓰지 않는다.
1. [Ollama](https://ollama.com/download)를 설치하고 실행한다.
2. `ollama pull qwen3-vl:8b-instruct` (6.2GB, 실행 중 메모리 약 10GB)
3. `RECOGNIZER=ollama .venv/bin/streamlit run app.py`

`qwen3-vl:8b`(thinking 버전)는 답하기 전에 생각 단계를 거쳐 같은 영수증에 약 3배 오래 걸린다.
정답 라벨링 규칙은 `eval/LABELING.md`에 있다. 실물 영수증 사진(`eval/images/real/`)은 커밋하지 않는다.

## Streamlit Community Cloud 배포
배포와 키 입력은 저장소 소유자가 직접 한다.

1. 이 브랜치의 PR을 main에 머지한다. Cloud는 main을 배포한다.
2. [share.streamlit.io](https://share.streamlit.io)에 GitHub 계정으로 로그인하고 **Create app**에서 GitHub 저장소로 배포하는 항목을 고른다(메뉴 이름은 바뀔 수 있다).
3. Repository `KJM0424/travel-bill-wanted1`, Branch `main`, Main file path `app.py`를 입력한다.
4. **Advanced settings**에서 Python 3.12를 고르고, Secrets에 아래를 넣는다.
   ```toml
   GEMINI_API_KEY = "발급받은 키"
   GEMINI_MODEL = "gemini-3.5-flash"
   APP_PASSWORD = "데모 비밀번호"
   RECOGNIZER = "gemini"
   ```
   쓰지 않는 키는 빈 문자열로 두지 말고 줄을 빼야 한다. Streamlit은 Secrets 값으로 같은 이름의 환경변수를 덮어쓴다.
5. **Deploy**를 누른다. 패키지는 `requirements.txt`로 설치된다.
6. 배포 URL에서 확인한다: 비밀번호 화면 → 실제 영수증 3장 업로드 → 검토 → 정산 화면에 송금 메시지가 나오는지.

## 데이터와 개인정보
- 업로드한 이미지는 서버 디스크에 저장하지 않는다. AI로 보내기 전에 EXIF를 지우고 긴 변을 1500px로 줄인다.
- 카드번호·승인번호는 추출하지 않는다. 스키마와 프롬프트 양쪽에 명시했다.
- 이미지는 Google Gemini API로 전송된다. 업로드 화면에 이 사실과 "카드번호·이름은 가리고 올려 주세요" 안내를 띄운다.
- 무료 등급 데이터 정책: 설계 단계에서 "무료 등급 입력은 서비스 개선에 쓰일 수 있다"로 정리했다. 이 저장소에서 약관 원문을 다시 확인한 기록은 없으므로, 배포 전에 [Gemini API 추가 약관](https://ai.google.dev/gemini-api/terms)에서 현재 내용을 확인한다.

## 한계
- 원화(KRW)만 지원한다. 외화 영수증은 경고하고 제외한다.
- 품목 단위로 나누지 않는다. 한 결제 건의 금액을 체크한 참석자에게 1/N로 나누고, 1원 단위 나머지는 결제자가 부담한다.
- 로그인과 저장소가 없다. 새로고침하면 상태가 사라지므로 결과 JSON을 내려받아 두고 다시 불러온다.
- 송금 링크에 금액이 미리 채워지는지는 확인하지 않았다. 메시지에 금액을 텍스트로 함께 넣는다.
- 교통비(렌터카·주유·배표)와 직접 추가한 지출은 한 장소가 아니어서 지도에 찍지 않는다. 금액은 요약과 날짜별 합계에 포함한다.
- Gemini와 로컬 모델(Ollama)의 정확도 비교는 다음 단계다.

## 구조
- `app.py`, `ui/`: 화면(단계별 렌더링, 세션 상태)
- `core/`: 스키마, 설정, 이미지 정규화, 인식기(Gemini·Mock), 결제 건 변환, 정산 계산, 송금 메시지. `streamlit`을 import하지 않는다(`core/config.py`의 선택적 import 제외).
- `prompts/`: 인식 프롬프트 버전. 바꾸면 `docs/ai-log.md`에 기록한다.
- `eval/`: 정답 라벨, 평가 지표, 샘플 영수증 생성기
- 설계: `docs/superpowers/specs/2026-11-01-trip-receipt-split-design.md`, 구현 계획: `docs/superpowers/plans/2026-11-01-trip-receipt-split.md`
