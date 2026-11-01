# 여행 영수증 정산 앱 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 여행 영수증 이미지를 여러 장 올리면 Gemini가 인식한다. 결제 건마다 결제자와 참석자를 정하면 사람별 정산액과 송금 메시지가 나오는 Streamlit 앱을 만든다.

**Architecture:** 화면은 `app.py`와 `ui/`가 맡는다. 계산과 외부 호출은 `core/`에 둔다. `core/`는 Streamlit 없이 import할 수 있어야 하고, pytest와 평가 스크립트가 그대로 쓴다. 모든 모듈은 `core/schema.py`의 pydantic 모델(`Receipt`, `Expense`, `Trip`)을 공통 계약으로 쓴다. 인식은 `Recognizer` 프로토콜 뒤에 Gemini 구현과 Mock 구현을 둔다.

**Tech Stack:** Python 3.12, Streamlit, google-genai, pydantic v2, Pillow + pillow-heif, pandas, requests, folium + streamlit-folium, python-dotenv, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-11-01-trip-receipt-split-design.md`

## Global Constraints

- 통화는 KRW만 지원한다. `currency != "KRW"`인 인식 결과는 경고하고 제외한다.
- `total_amount`는 할인·포인트를 반영한 실제 결제 금액이다. 프롬프트와 라벨링 규칙에 같은 정의를 쓴다.
- 카드번호·승인번호는 추출하지 않는다. 스키마에 해당 필드를 두지 않고, 프롬프트에도 명시한다.
- 업로드 이미지는 디스크에 저장하지 않는다. AI로 보내기 전에 EXIF를 제거하고, 긴 변을 1500px로 줄인다.
- 1회 업로드는 최대 30장이다. 인식은 3장씩 병렬로 처리한다.
- 회비 지갑 이름은 `"회비 지갑"`이다. 참석자 이름으로 쓸 수 없다.
- 1원 단위 나머지는 결제자가 부담한다. 결제자가 회비 지갑이면 지갑이 부담한다.
- 중복 의심 기준: 금액이 같고 시각 차이가 ±10분 이내다.
- 키(`GEMINI_API_KEY`, `KAKAO_REST_API_KEY`, `APP_PASSWORD`)는 로컬에서는 `.env`, 배포에서는 `st.secrets`에서 읽는다. 저장소에 커밋하지 않는다.
- `core/`는 `streamlit`을 import하지 않는다. 예외는 `core/config.py`의 선택적 import다.

## Review Focus

1. **참석자 이름 문제:** 같은 이름이 두 번 들어가거나, 공백뿐이거나, `"회비 지갑"`이면 여행 설정 단계에서 막고 이유를 보여 준다. 테스트는 Task 2에 있다.
2. **참석자 목록을 바꿨을 때:** 설정으로 돌아가 사람을 빼면 기존 결제 건의 참석자에서도 빠진다. 결제자가 빠진 사람이면 대표로 바뀐다. 정산이 깨지면 안 된다. 테스트는 Task 11에 있다.
3. **결제자가 그 건의 참석자가 아닐 때:** 결제만 하고 먹지 않은 경우다. 결제자는 낸 돈 전액을 돌려받고, 부담액은 0원이다. 테스트는 Task 3에 있다.
4. **받는 사람의 송금 정보가 없을 때:** 메시지가 깨지지 않는다. 금액과 함께 "받는 분께 계좌를 확인하세요"를 넣는다. 테스트는 Task 4에 있다.
5. **금액이 0원이거나 비어 있는 결제 건:** 인식 실패, 수동 입력 누락 같은 경우다. 정산 단계로 넘어가지 못하게 막고, 어느 건인지 알려 준다. 테스트는 Task 3(`readiness_errors`)에 있다.

---

## 작업 공간(Orca worktree)과 태스크 배치

| 단계 | 브랜치 | 태스크 | 시작 조건 |
|---|---|---|---|
| 0 | `feature/scaffold` (main 작업 공간) | 1, 2 | 없음 |
| 1A | `feature/settlement` | 3, 4 | 0 머지 |
| 1B | `feature/recognizer` | 5, 6, 7, 8, 9, 10 | 0 머지 |
| 2 | `feature/ui` | 11, 12, 13, 14, 15 | 1A, 1B 머지 |
| 3A | `feature/prompt-v2` | 16 | 1B 머지 + 테스트셋 라벨링 완료 |
| 3B | `feature/map` (선택) | 17, 18 | 2 머지 |
| 4 | `feature/hardening` | 19 | 2 머지 |

- 1A와 1B, 3A와 3B는 동시에 진행할 수 있다.
- UI는 인식 결과를 결제 건으로 바꾸는 `expense_builder`(Task 8)가 필요해서 1B도 기다린다. 스펙의 표에서는 settlement만 기다리게 되어 있었는데, 이 점을 보정했다.
- 각 작업 공간은 최신 main에서 만들고, 시작할 때 `scripts/setup_worktree.sh`를 실행한다.

---

## 단계 0 — `feature/scaffold`

### Task 1: 프로젝트 뼈대와 설정 로딩

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.gitignore`, `.env.example`, `.streamlit/secrets.toml.example`, `CLAUDE.md`, `scripts/setup_worktree.sh`, `core/__init__.py`, `core/config.py`, `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `get_setting(name: str, default: str | None = None) -> str | None`
  - 조회 순서: `st.secrets`(streamlit을 import할 수 있고 secrets가 있을 때) → `os.environ`(`.env`를 `load_dotenv()`로 읽음) → `default`

- [ ] **Step 1: 의존성과 설정 파일 작성**
  - `requirements.txt`: `streamlit>=1.40`, `google-genai>=1.0`, `pydantic>=2.7`, `pillow>=10.4`, `pillow-heif>=0.18`, `pandas>=2.2`, `requests>=2.32`, `folium>=0.17`, `streamlit-folium>=0.22`, `python-dotenv>=1.0`
  - `requirements-dev.txt`: `-r requirements.txt`, `pytest>=8`, `ruff>=0.6`
  - `pyproject.toml`: `[tool.ruff] line-length = 100, target-version = "py312"`, `[tool.pytest.ini_options] testpaths = ["tests"]`
  - `.gitignore`: `.env`, `.venv/`, `.streamlit/secrets.toml`, `__pycache__/`, `eval/images/real/`, `eval/results/*.json`
  - 실물 영수증 사진과 원본 결과는 커밋하지 않는다. 결과는 요약 CSV만 커밋한다.
  - `.env.example`과 `secrets.toml.example`에는 값 없이 키 이름만 적는다: `GEMINI_API_KEY`, `GEMINI_MODEL`, `KAKAO_REST_API_KEY`, `APP_PASSWORD`, `RECOGNIZER`(`gemini`|`mock`)

- [ ] **Step 2: `scripts/setup_worktree.sh` 작성**
  - `python3.12 -m venv .venv`를 실행한다. `python3.12`가 없으면 `python3`로 대신하고 버전을 출력한다.
  - `.venv/bin/pip install -r requirements-dev.txt`
  - `.env`가 없으면 `git worktree list --porcelain`의 첫 worktree(main)에서 `.env`를 복사한다. 그것도 없으면 `.env.example`을 복사하고 "키를 채우세요"를 출력한다.
  - 실행 권한을 준다(`chmod +x`).

- [ ] **Step 3: `CLAUDE.md` 작성**
  - 담을 내용: 스펙·계획 경로, `core/`에 streamlit import 금지, 테스트 실행 명령(`.venv/bin/pytest`), 린트 명령(`ruff check . && ruff format --check .`), 키를 커밋하지 않는다는 규칙
  - 프롬프트를 바꾸면 `docs/ai-log.md`에 기록한다는 규칙도 넣는다.

- [ ] **Step 4: 실패하는 테스트 작성** — `tests/test_config.py`

```python
def test_get_setting_reads_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    assert get_setting("GEMINI_MODEL") == "test-model"

def test_get_setting_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert get_setting("NOPE_KEY", "fallback") == "fallback"
```

- [ ] **Step 5: 셋업 후 테스트 실행해 실패 확인**
  - Run: `./scripts/setup_worktree.sh && .venv/bin/pytest tests/test_config.py -v`
  - Expected: FAIL (`ImportError: cannot import name 'get_setting'`)

- [ ] **Step 6: `core/config.py`에 `get_setting` 구현**
  - `st.secrets` 접근은 `try/except Exception`으로 감싼다. secrets 파일이 없으면 Streamlit이 예외를 던지기 때문이다.

- [ ] **Step 7: 테스트 통과 확인**
  - Run: `.venv/bin/pytest tests/test_config.py -v && .venv/bin/ruff check .`
  - Expected: 2 passed, ruff 오류 0

- [ ] **Step 8: 커밋**
```bash
git add requirements*.txt pyproject.toml .gitignore .env.example .streamlit/secrets.toml.example CLAUDE.md scripts core tests
git commit -m "chore: 프로젝트 뼈대와 설정 로딩 추가"
```

### Task 2: 공통 스키마 (`core/schema.py`)

**Files:**
- Create: `core/schema.py`, `tests/test_schema.py`

**Interfaces:**
- Produces:
```python
FUND_WALLET = "회비 지갑"
DocType = Literal["receipt", "booking_capture", "card_slip", "not_receipt"]
Category = Literal["food", "cafe", "lodging", "transport", "shopping", "activity", "etc"]

class LineItem(BaseModel): name: str; amount: int

class Receipt(BaseModel):            # AI 인식 결과 (Gemini response_schema로도 사용)
    doc_type: DocType
    merchant_name: str | None
    merchant_address: str | None
    paid_at: str | None              # "YYYY-MM-DDTHH:MM" 또는 날짜만 "YYYY-MM-DD"
    total_amount: int | None
    currency: str                    # 기본 "KRW"
    category: Category
    items: list[LineItem]            # 기본 []
    warnings: list[str]              # 기본 []

class Expense(BaseModel):            # 정산 단위 (사용자가 수정 가능)
    expense_id: str
    source: Literal["ai", "manual"]
    merchant_name: str
    merchant_address: str | None = None
    paid_at: datetime | None = None
    time_known: bool = False         # False면 그 날짜 맨 앞에 정렬
    amount: int                      # >= 0, 0은 readiness에서 막음
    category: Category = "etc"
    payer: str                       # 참석자 이름 또는 FUND_WALLET
    participants: list[str]          # 빈 리스트 허용, readiness에서 막음
    excluded: bool = False           # 중복 등으로 정산에서 제외
    image_hash: str | None = None
    warnings: list[str] = []

class PayoutInfo(BaseModel):
    bank_account: str | None = None
    toss_link: str | None = None
    kakaopay_link: str | None = None

class Trip(BaseModel):
    name: str
    members: list[str]
    leader: str
    mode: Literal["prepaid", "fund"]
    fund_per_person: int = 0
    start_date: date
    end_date: date
    payout: dict[str, PayoutInfo] = {}
    expenses: list[Expense] = []

def parse_paid_at(value: str | None) -> tuple[datetime | None, bool]   # (값, time_known)
```

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_schema.py`

```python
def make_trip(**overrides):
    base = dict(name="제주", members=["민수", "지영", "철수"], leader="민수", mode="prepaid",
                start_date=date(2026, 10, 10), end_date=date(2026, 10, 12))
    return Trip(**(base | overrides))

def test_trip_strips_member_names():
    assert make_trip(members=[" 민수 ", "지영"]).members == ["민수", "지영"]

@pytest.mark.parametrize("members", [["민수", "민수"], ["민수", "  "], ["민수", "회비 지갑"], []])
def test_trip_rejects_bad_members(members):
    with pytest.raises(ValidationError):
        make_trip(members=members)

def test_trip_rejects_leader_not_in_members():
    with pytest.raises(ValidationError):
        make_trip(leader="영희")

def test_trip_rejects_end_before_start():
    with pytest.raises(ValidationError):
        make_trip(end_date=date(2026, 10, 9))

def test_fund_mode_requires_positive_fee():
    with pytest.raises(ValidationError):
        make_trip(mode="fund", fund_per_person=0)

def test_expense_rejects_negative_amount():
    with pytest.raises(ValidationError):
        Expense(expense_id="e1", source="manual", merchant_name="x", amount=-1, payer="민수", participants=[])

def test_parse_paid_at_with_time():
    assert parse_paid_at("2026-10-12T19:42") == (datetime(2026, 10, 12, 19, 42), True)

def test_parse_paid_at_date_only():
    assert parse_paid_at("2026-10-12") == (datetime(2026, 10, 12), False)

@pytest.mark.parametrize("value", [None, "", "어제 저녁", "2026-13-01"])
def test_parse_paid_at_invalid_returns_none(value):
    assert parse_paid_at(value) == (None, False)

def test_receipt_schema_has_no_card_number_field():
    props = Receipt.model_json_schema()["properties"]
    assert not any(k in props for k in ["card_number", "approval_number", "phone"])
```

- [ ] **Step 2: 실패 확인**
  - Run: `.venv/bin/pytest tests/test_schema.py -v`
  - Expected: FAIL (`ImportError`)

- [ ] **Step 3: `core/schema.py` 구현**
  - `Trip`은 `field_validator("members")`로 strip·빈 이름·중복·FUND_WALLET 이름을 검사하고, 1명 이상인지 확인한다.
  - `model_validator(mode="after")`로 leader가 members에 있는지, 날짜 순서가 맞는지, 회비형이면 회비가 0보다 큰지 검사한다.
  - 오류 메시지는 화면에 그대로 보여 줄 한국어로 쓴다(예: `"참석자 이름이 중복됩니다: 민수"`).
  - `Expense.amount`는 `Field(ge=0)`로 둔다.

- [ ] **Step 4: 통과 확인**
  - Run: `.venv/bin/pytest -v`
  - Expected: 전부 PASS

- [ ] **Step 5: 커밋 후 main에 머지**
```bash
git add core/schema.py tests/test_schema.py
git commit -m "feat: 인식 결과·결제 건·여행 공통 스키마 추가"
```
  - `feature/design-spec`과 `feature/scaffold`를 main에 머지한다. GitHub 저장소를 연결했다면 PR로 머지한다.

---

## 단계 1A — `feature/settlement`

### Task 3: 정산 계산 (`core/settlement.py`)

**Files:**
- Create: `core/settlement.py`, `tests/test_settlement.py`

**Interfaces:**
- Consumes: `Trip`, `Expense`, `FUND_WALLET` (Task 2)
- Produces:
```python
@dataclass(frozen=True)
class Balance: name: str; paid: int; owed: int; net: int    # net = paid - owed
@dataclass(frozen=True)
class Transfer: sender: str; receiver: str; amount: int

def readiness_errors(trip: Trip) -> list[str]
def compute_balances(trip: Trip) -> list[Balance]          # members 순서, 회비형이면 FUND_WALLET이 마지막
def plan_transfers(balances: list[Balance]) -> list[Transfer]
```

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_settlement.py`
  - 헬퍼: `exp(amount, payer, participants, excluded=False)`는 Expense를 만든다. `trip(mode, expenses, fee=0)`은 members `["A", "B", "C"]`, leader `"A"`로 여행을 만든다.

```python
def test_prepaid_even_split():
    b = by_name(compute_balances(trip("prepaid", [exp(30000, "A", ["A", "B", "C"])])))
    assert (b["A"].net, b["B"].net, b["C"].net) == (20000, -10000, -10000)

def test_absent_member_excluded_from_share():          # 카페에 C가 빠짐
    b = by_name(compute_balances(trip("prepaid", [exp(10000, "A", ["A", "B"])])))
    assert (b["A"].net, b["B"].net, b["C"].net) == (5000, -5000, 0)

def test_payer_not_participant_gets_full_refund():     # Review Focus 3
    b = by_name(compute_balances(trip("prepaid", [exp(9000, "A", ["B", "C"])])))
    assert (b["A"].paid, b["A"].owed, b["A"].net) == (9000, 0, 9000)

def test_remainder_charged_to_payer():
    b = by_name(compute_balances(trip("prepaid", [exp(10000, "B", ["A", "B", "C"])])))
    assert (b["A"].owed, b["B"].owed, b["C"].owed) == (3333, 3334, 3333)

def test_remainder_charged_to_payer_even_if_not_participant():
    b = by_name(compute_balances(trip("prepaid", [exp(11, "A", ["B", "C"])])))
    assert (b["A"].owed, b["B"].owed, b["C"].owed) == (1, 5, 5)

def test_multiple_payers():
    b = by_name(compute_balances(trip("prepaid", [exp(30000, "A", ["A", "B", "C"]),
                                                  exp(60000, "B", ["A", "B", "C"])])))
    assert (b["A"].net, b["B"].net, b["C"].net) == (0, 30000, -30000)

def test_fund_mode_refund_when_underspent():
    b = by_name(compute_balances(trip("fund", [exp(60000, FUND_WALLET, ["A", "B", "C"])], fee=30000)))
    assert b[FUND_WALLET].net == -30000 and b["A"].net == 10000

def test_fund_mode_shortfall():
    b = by_name(compute_balances(trip("fund", [exp(120000, FUND_WALLET, ["A", "B", "C"])], fee=30000)))
    assert b[FUND_WALLET].net == 30000 and b["A"].net == -10000

def test_fund_mode_personal_payment():
    b = by_name(compute_balances(trip("fund", [exp(90000, FUND_WALLET, ["A", "B", "C"]),
                                               exp(6000, "B", ["A", "B", "C"])], fee=30000)))
    assert (b["B"].net, b[FUND_WALLET].net) == (4000, 0)

def test_excluded_expense_ignored():
    b = by_name(compute_balances(trip("prepaid", [exp(30000, "A", ["A", "B", "C"], excluded=True)])))
    assert all(x.net == 0 for x in b.values())

def test_nets_always_sum_to_zero():
    t = trip("fund", [exp(10001, "B", ["A", "C"]), exp(77777, FUND_WALLET, ["A", "B", "C"])], fee=25000)
    assert sum(x.net for x in compute_balances(t)) == 0

def test_plan_transfers_settles_everyone():
    bal = compute_balances(trip("prepaid", [exp(30000, "A", ["A", "B", "C"]), exp(60000, "B", ["A", "B", "C"])]))
    assert plan_transfers(bal) == [Transfer("C", "B", 30000)]

def test_plan_transfers_skips_zero_and_is_deterministic():
    bal = [Balance("A", 0, 0, 0), Balance("B", 0, 5000, -5000), Balance("C", 5000, 0, 5000)]
    assert plan_transfers(bal) == plan_transfers(list(reversed(bal))) == [Transfer("B", "C", 5000)]

def test_readiness_errors():                          # Review Focus 5 + 빈 상태
    assert readiness_errors(trip("prepaid", [])) == ["결제 건이 없습니다."]
    errs = readiness_errors(trip("prepaid", [exp(0, "A", ["A"]), exp(5000, "A", [])]))
    assert any("금액" in e for e in errs) and any("참석자" in e for e in errs)

def test_readiness_ignores_excluded():
    assert readiness_errors(trip("prepaid", [exp(5000, "A", ["A"]), exp(0, "A", [], excluded=True)])) == []
```

- [ ] **Step 2: 실패 확인**
  - Run: `.venv/bin/pytest tests/test_settlement.py -v`
  - Expected: FAIL (`ImportError`)

- [ ] **Step 3: 구현**
  - `compute_balances`
    - excluded가 아닌 건만 계산한다.
    - `share = amount // len(participants)`를 각 참석자의 owed에 더한다.
    - `amount - share * len(participants)`를 payer의 owed에 더한다.
    - payer의 paid에는 amount를 더한다.
    - 회비형이면 각 member의 paid에 회비를 더하고, `FUND_WALLET`의 owed에 `회비 × 인원`을 더한다.
  - `plan_transfers`의 그리디 알고리즘
```python
debtors = sorted(([b.name, -b.net] for b in balances if b.net < 0), key=lambda x: (-x[1], x[0]))
creditors = sorted(([b.name, b.net] for b in balances if b.net > 0), key=lambda x: (-x[1], x[0]))
i = j = 0
while i < len(debtors) and j < len(creditors):
    amount = min(debtors[i][1], creditors[j][1])
    transfers.append(Transfer(debtors[i][0], creditors[j][0], amount))
    debtors[i][1] -= amount; creditors[j][1] -= amount
    i += debtors[i][1] == 0; j += creditors[j][1] == 0
```
  - `readiness_errors`가 반환할 메시지: `"결제 건이 없습니다."`, `"'{merchant}' 금액이 0원입니다."`, `"'{merchant}' 참석자가 없습니다."`, `"'{merchant}' 결제자가 여행 참석자가 아닙니다."`. 결제자가 그 건의 참석자가 아닌 것은 허용하므로 오류로 보지 않는다.

- [ ] **Step 4: 통과 확인**
  - Run: `.venv/bin/pytest tests/test_settlement.py -v`
  - Expected: 전부 PASS

- [ ] **Step 5: 커밋**
```bash
git add core/settlement.py tests/test_settlement.py
git commit -m "feat: 선결제형·회비형 정산 계산과 송금 경로 추가"
```

### Task 4: 송금 메시지 (`core/payment_message.py`)

**Files:**
- Create: `core/payment_message.py`, `tests/test_payment_message.py`

**Interfaces:**
- Consumes: `Transfer` (Task 3), `Trip`, `PayoutInfo`, `FUND_WALLET` (Task 2)
- Produces:
  - `format_won(amount: int) -> str`: `12345 → "12,345원"`
  - `build_message(transfer: Transfer, trip: Trip) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_format_won():
    assert format_won(12345) == "12,345원"

def test_message_includes_amount_and_all_payout_channels():
    t = trip_with_payout("A", PayoutInfo(bank_account="카카오뱅크 3333-01-1234567",
                                         toss_link="https://toss.me/minsu",
                                         kakaopay_link="https://qr.kakaopay.com/abc"))
    msg = build_message(Transfer("B", "A", 15000), t)
    for part in ["B", "A", "15,000원", "3333-01-1234567", "https://toss.me/minsu", "https://qr.kakaopay.com/abc"]:
        assert part in msg

def test_message_without_payout_info():                # Review Focus 4
    msg = build_message(Transfer("B", "C", 5000), trip_with_payout("A", PayoutInfo()))
    assert "5,000원" in msg and "받는 분께 계좌를 확인하세요" in msg

def test_fund_wallet_receiver_uses_leader_payout():
    t = trip_with_payout("A", PayoutInfo(toss_link="https://toss.me/minsu"), mode="fund")
    msg = build_message(Transfer("B", FUND_WALLET, 7000), t)
    assert "https://toss.me/minsu" in msg and "회비 지갑(대표 A)" in msg

def test_fund_wallet_sender_is_refund_message():
    msg = build_message(Transfer(FUND_WALLET, "B", 7000), trip_with_payout("A", PayoutInfo(), mode="fund"))
    assert "환급" in msg and "A" in msg
```

- [ ] **Step 2: 실패 확인**
  - Run: `.venv/bin/pytest tests/test_payment_message.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**
  - 받는 사람이 회비 지갑이면 leader의 송금 정보를 쓴다.
  - 보내는 사람이 회비 지갑이면 문구를 `"[{trip.name}] 대표 {leader}님이 {receiver}님께 회비 {금액}을 환급합니다."`로 쓴다.
  - 기본 문구 첫 줄: `"[{trip.name}] {sender}님 → {receiver}님 {금액}"`
  - 이어서 정보가 있는 송금 수단만 줄마다 넣는다. 하나도 없으면 안내 문구를 넣는다.
  - 링크에 금액을 미리 채우는 기능은 1일차에 확인한 뒤 결정한다. 이 태스크에서는 링크를 그대로 넣는다.

- [ ] **Step 4: 통과 확인 후 커밋**
  - Run: `.venv/bin/pytest -v`
  - Expected: 전부 PASS
```bash
git add core/payment_message.py tests/test_payment_message.py
git commit -m "feat: 사람별 송금 메시지 생성 추가"
```
  - `feature/settlement`를 main에 머지한다.

---

## 단계 1B — `feature/recognizer`

### Task 5: 이미지 정규화 (`core/image_utils.py`)

**Files:**
- Create: `core/image_utils.py`, `tests/test_image_utils.py`

**Interfaces:**
- Produces:
  - `MAX_LONG_SIDE = 1500`
  - `class UnsupportedImageError(ValueError)`
  - `image_hash(raw: bytes) -> str`: sha256 hex
  - `normalize_image(raw: bytes) -> bytes`: JPEG(quality 85), EXIF 제거, 회전 보정, 긴 변 1500px 이하

- [ ] **Step 1: 실패하는 테스트 작성**
  - 테스트 이미지는 Pillow로 메모리에서 만든다.

```python
def test_normalize_shrinks_long_side():
    out = Image.open(io.BytesIO(normalize_image(make_png(3000, 1000))))
    assert max(out.size) == 1500 and out.format == "JPEG"

def test_normalize_keeps_small_image_size():
    assert Image.open(io.BytesIO(normalize_image(make_png(800, 600)))).size == (800, 600)

def test_normalize_strips_exif():
    out = Image.open(io.BytesIO(normalize_image(make_jpeg_with_exif_gps())))
    assert not out.getexif()

def test_normalize_rejects_non_image():
    with pytest.raises(UnsupportedImageError):
        normalize_image(b"%PDF-1.4 not an image")

def test_image_hash_is_stable():
    data = make_png(10, 10)
    assert image_hash(data) == image_hash(data) and len(image_hash(data)) == 64
```

- [ ] **Step 2: 실패 확인**
  - Run: `.venv/bin/pytest tests/test_image_utils.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**
  - 모듈을 불러올 때 `pillow_heif.register_heif_opener()`를 호출한다.
  - `ImageOps.exif_transpose`로 회전을 보정하고, `convert("RGB")`, `thumbnail((1500, 1500))`을 거쳐 `exif` 인자 없이 저장한다.
  - `PIL.UnidentifiedImageError`는 `UnsupportedImageError("이미지 파일이 아닙니다")`로 바꿔서 던진다.

- [ ] **Step 4: 통과 확인 후 커밋**
  - Run: `.venv/bin/pytest tests/test_image_utils.py -v`
  - Expected: PASS
```bash
git add core/image_utils.py tests/test_image_utils.py
git commit -m "feat: 업로드 이미지 리사이즈·EXIF 제거 추가"
```

### Task 6: 인식기 인터페이스, Mock, 프롬프트 v1

**Files:**
- Create: `core/recognizer/__init__.py`, `core/recognizer/base.py`, `core/recognizer/mock.py`, `prompts/v1.md`, `tests/fixtures/receipts/*.json`(4개), `tests/test_recognizer_base.py`

**Interfaces:**
- Consumes: `Receipt` (Task 2), `image_hash` (Task 5)
- Produces:
```python
class RecognitionError(Exception): ...
class Recognizer(Protocol):
    def recognize(self, image: bytes, prompt_version: str) -> Receipt: ...
def load_prompt(version: str) -> str                       # prompts/{version}.md
class MockRecognizer:                                      # Recognizer 구현
    def __init__(self, fixtures_dir: Path = Path("tests/fixtures/receipts")): ...
    def recognize(self, image: bytes, prompt_version: str) -> Receipt
```

- [ ] **Step 1: fixture 4개 작성**
  - `food.json`: 흑돼지 96,000원, 시간 있음
  - `cafe.json`: 18,000원
  - `booking.json`: `booking_capture`, 날짜만 있음
  - `not_receipt.json`: `not_receipt`, 금액 null
  - 모두 `Receipt` 형식을 따른다. 날짜는 2026-10-10 ~ 2026-10-12다.

- [ ] **Step 2: `prompts/v1.md` 작성**
  - 단순한 첫 버전이다.
  - 역할: 한국 영수증·예약 캡처 인식기
  - 출력: 스키마 필드 설명
  - `total_amount`는 실제 결제 금액
  - 카드번호·승인번호·전화번호는 출력하지 않는다
  - 영수증이 아니면 `doc_type="not_receipt"`
  - 날짜 형식은 `YYYY-MM-DDTHH:MM`, 시간이 없으면 `YYYY-MM-DD`

- [ ] **Step 3: 실패하는 테스트 작성**

```python
def test_load_prompt_v1_mentions_actual_paid_amount():
    assert "실제 결제" in load_prompt("v1")

def test_load_prompt_unknown_version():
    with pytest.raises(ValueError):
        load_prompt("v999")

def test_mock_is_deterministic_per_image():
    m = MockRecognizer()
    assert m.recognize(b"img-1", "v1") == m.recognize(b"img-1", "v1")

def test_mock_returns_valid_receipts_for_all_fixtures():
    m = MockRecognizer()
    kinds = {m.recognize(bytes([i]), "v1").doc_type for i in range(40)}
    assert {"receipt", "not_receipt"} <= kinds
```

- [ ] **Step 4: 실패 확인 → 구현 → 통과 확인**
  - Run: `.venv/bin/pytest tests/test_recognizer_base.py -v`
  - MockRecognizer는 정렬한 fixture 목록에서 `int(image_hash(image), 16) % len(fixtures)` 위치의 fixture를 반환한다.

- [ ] **Step 5: 커밋**
```bash
git add core/recognizer prompts tests/fixtures tests/test_recognizer_base.py
git commit -m "feat: 인식기 인터페이스·Mock·프롬프트 v1 추가"
```

### Task 7: Gemini 인식기 (`core/recognizer/gemini.py`)

**Files:**
- Create: `core/recognizer/gemini.py`, `tests/test_gemini_recognizer.py`

**Interfaces:**
- Consumes: `Receipt`, `load_prompt`, `RecognitionError`
- Produces:
```python
DEFAULT_MODEL = "gemini-2.5-flash"     # Step 1에서 실제로 쓸 수 있는 모델명으로 확정
class GeminiRecognizer:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client=None,
                 sleep=time.sleep, max_rate_retries: int = 3): ...
    def recognize(self, image: bytes, prompt_version: str) -> Receipt
```

- [ ] **Step 1: 실제로 쓸 수 있는 모델명 확인 (사람과 함께, 키 필요)**
  - Run: `.venv/bin/python -c "from google import genai; import os; from dotenv import load_dotenv; load_dotenv(); c=genai.Client(api_key=os.environ['GEMINI_API_KEY']); print([m.name for m in c.models.list() if 'flash' in m.name])"`
  - Expected: flash 모델 목록이 나온다. 무료 등급에서 쓸 수 있는 최신 Flash로 `DEFAULT_MODEL`을 정하고, `.env`의 `GEMINI_MODEL`에도 적는다.

- [ ] **Step 2: 실패하는 테스트 작성**
  - 가짜 client를 주입해서 테스트한다. 네트워크는 쓰지 않는다.
  - 가짜 client의 `models.generate_content(...)`는 미리 정해 둔 응답 목록을 차례로 돌려준다. 응답은 `.text` 속성을 가진 객체이거나 던질 예외다.

```python
def test_returns_parsed_receipt():
    r = GeminiRecognizer("k", client=fake_client([ok_text(food_json)]), sleep=lambda s: None)
    assert r.recognize(b"img", "v1").total_amount == 96000

def test_sends_schema_and_prompt():
    client = fake_client([ok_text(food_json)])
    GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    call = client.calls[0]
    assert call["config"].response_mime_type == "application/json"
    assert any("실제 결제" in str(p) for p in call["contents"])

def test_retries_on_rate_limit_then_succeeds():
    sleeps = []
    client = fake_client([rate_limit_error(), rate_limit_error(), ok_text(food_json)])
    GeminiRecognizer("k", client=client, sleep=sleeps.append).recognize(b"img", "v1")
    assert sleeps == [1, 2]

def test_gives_up_after_rate_limit_retries():
    client = fake_client([rate_limit_error()] * 4)
    with pytest.raises(RecognitionError, match="한도"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")

def test_retries_once_on_invalid_json_then_fails():
    client = fake_client([ok_text("{not json"), ok_text('{"doc_type": "?"}')])
    with pytest.raises(RecognitionError, match="형식"):
        GeminiRecognizer("k", client=client, sleep=lambda s: None).recognize(b"img", "v1")
    assert len(client.calls) == 2

def test_missing_api_key():
    with pytest.raises(RecognitionError, match="API 키"):
        GeminiRecognizer("")
```
  - `rate_limit_error()`는 `google.genai.errors.APIError`의 code가 429인 인스턴스를 만든다. SDK의 생성자 시그니처를 확인해서 맞춘다.

- [ ] **Step 3: 실패 확인**
  - Run: `.venv/bin/pytest tests/test_gemini_recognizer.py -v`
  - Expected: FAIL

- [ ] **Step 4: 구현**
  - `contents=[types.Part.from_bytes(data=image, mime_type="image/jpeg"), load_prompt(prompt_version)]`
  - `config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Receipt, temperature=0)`
  - 429 오류가 나면 1, 2, 4초 간격으로 최대 `max_rate_retries`번 재시도한다.
  - `Receipt.model_validate_json(resp.text)`가 실패하면 1번 더 호출한다.
  - 그 밖의 예외는 `RecognitionError("AI 호출 실패: ...")`로 바꿔 던진다. 키 값은 메시지에 넣지 않는다.

- [ ] **Step 5: 통과 확인 후 실제 1장 스모크 테스트**
  - Run: `.venv/bin/pytest tests/test_gemini_recognizer.py -v`
  - Expected: PASS
  - 실제 영수증 1장을 `GeminiRecognizer`로 인식해서 출력되는 JSON을 눈으로 확인한다. 이 단계는 수동이고 키가 필요하다.

- [ ] **Step 6: 커밋**
```bash
git add core/recognizer/gemini.py tests/test_gemini_recognizer.py
git commit -m "feat: Gemini 영수증 인식기와 재시도 처리 추가"
```

### Task 8: 일괄 인식과 결제 건 변환

**Files:**
- Create: `core/recognize_service.py`, `core/expense_builder.py`, `tests/test_recognize_service.py`, `tests/test_expense_builder.py`

**Interfaces:**
- Consumes: `Recognizer`, `RecognitionError`, `normalize_image`, `image_hash`, `UnsupportedImageError`, `Receipt`, `Expense`, `Trip`, `parse_paid_at`, `FUND_WALLET`
- Produces:
```python
MAX_FILES = 30
@dataclass
class RecognitionOutcome:
    filename: str
    image_hash: str
    receipt: Receipt | None
    error: str | None
    elapsed_s: float

def recognize_batch(files: list[tuple[str, bytes]], recognizer: Recognizer, prompt_version: str,
                    cache: dict[str, Receipt], max_workers: int = 3,
                    on_progress: Callable[[int, int], None] | None = None) -> list[RecognitionOutcome]

def build_expenses(outcomes: list[RecognitionOutcome], trip: Trip) -> tuple[list[Expense], list[str]]
                                                    # (결제 건, 사용자 안내 메시지)
def sort_expenses(expenses: list[Expense]) -> list[Expense]
def find_duplicates(expenses: list[Expense]) -> list[tuple[str, str]]     # expense_id 쌍
```

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_recognize_service.py`

```python
def test_rejects_more_than_30_files():
    with pytest.raises(ValueError, match="30"):
        recognize_batch([("a.jpg", png())] * 31, MockRecognizer(), "v1", {})

def test_one_failure_does_not_stop_others():
    files = [("ok.png", png()), ("bad.pdf", b"%PDF"), ("ok2.png", png(color="red"))]
    out = recognize_batch(files, MockRecognizer(), "v1", {})
    assert [o.error is None for o in out] == [True, False, True]
    assert "이미지 파일이 아닙니다" in out[1].error

def test_keeps_input_order():
    files = [(f"{i}.png", png(color=(i, 0, 0))) for i in range(6)]
    assert [o.filename for o in recognize_batch(files, MockRecognizer(), "v1", {})] == [f for f, _ in files]

def test_cache_avoids_second_call():
    counting = CountingRecognizer(MockRecognizer())
    cache = {}
    recognize_batch([("a.png", png())], counting, "v1", cache)
    recognize_batch([("a.png", png())], counting, "v1", cache)
    assert counting.calls == 1

def test_recognition_error_becomes_outcome_error():
    out = recognize_batch([("a.png", png())], AlwaysFails("AI 호출 실패: 시간 초과"), "v1", {})
    assert out[0].receipt is None and "시간 초과" in out[0].error

def test_progress_callback_reaches_total():
    seen = []
    recognize_batch([("a.png", png()), ("b.png", png(color="blue"))], MockRecognizer(), "v1", {},
                    on_progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (2, 2)
```

- [ ] **Step 2: 실패하는 테스트 작성** — `tests/test_expense_builder.py`
  - 여행 날짜는 2026-10-10 ~ 2026-10-12, members는 `["A", "B", "C"]`, leader는 `"A"`다.

```python
def test_receipt_becomes_expense_with_defaults():
    exps, notes = build_expenses([outcome(receipt(total=96000, paid_at="2026-10-11T19:42"))], prepaid_trip)
    e = exps[0]
    assert (e.amount, e.payer, e.participants, e.time_known) == (96000, "A", ["A", "B", "C"], True)

def test_fund_mode_default_payer_is_wallet():
    exps, _ = build_expenses([outcome(receipt())], fund_trip)
    assert exps[0].payer == FUND_WALLET

def test_not_receipt_and_foreign_currency_are_excluded_with_notice():
    exps, notes = build_expenses([outcome(receipt(doc_type="not_receipt"), name="cat.jpg"),
                                  outcome(receipt(currency="JPY"), name="tokyo.jpg")], prepaid_trip)
    assert exps == [] and any("cat.jpg" in n for n in notes) and any("tokyo.jpg" in n for n in notes)

def test_failed_outcome_becomes_notice():
    _, notes = build_expenses([failed_outcome("x.jpg", "AI 호출 실패")], prepaid_trip)
    assert any("x.jpg" in n and "수동" in n for n in notes)

def test_missing_amount_becomes_zero_with_warning():
    exps, _ = build_expenses([outcome(receipt(total=None))], prepaid_trip)
    assert exps[0].amount == 0 and any("금액" in w for w in exps[0].warnings)

def test_wrong_year_corrected_to_trip_year():
    exps, _ = build_expenses([outcome(receipt(paid_at="2025-10-11T12:00"))], prepaid_trip)
    assert exps[0].paid_at.year == 2026 and any("연도" in w for w in exps[0].warnings)

def test_out_of_range_date_warns_but_keeps():
    exps, _ = build_expenses([outcome(receipt(paid_at="2026-09-01"))], prepaid_trip)
    assert len(exps) == 1 and any("여행 기간" in w for w in exps[0].warnings)

def test_sort_date_only_first_in_day_and_unknown_last():
    a = mk(paid_at=datetime(2026, 10, 11, 9, 0), time_known=True, id="a")
    b = mk(paid_at=datetime(2026, 10, 11), time_known=False, id="b")
    c = mk(paid_at=None, id="c")
    d = mk(paid_at=datetime(2026, 10, 10, 20, 0), time_known=True, id="d")
    assert [e.expense_id for e in sort_expenses([a, b, c, d])] == ["d", "b", "a", "c"]

def test_find_duplicates_within_10_minutes_same_amount():
    a = mk(amount=18000, paid_at=datetime(2026, 10, 11, 15, 0), time_known=True, id="a")
    b = mk(amount=18000, paid_at=datetime(2026, 10, 11, 15, 9), time_known=True, id="b")
    c = mk(amount=18000, paid_at=datetime(2026, 10, 11, 15, 30), time_known=True, id="c")
    assert find_duplicates([a, b, c]) == [("a", "b")]
```

- [ ] **Step 3: 실패 확인**
  - Run: `.venv/bin/pytest tests/test_recognize_service.py tests/test_expense_builder.py -v`
  - Expected: FAIL

- [ ] **Step 4: 구현**
  - `recognize_batch`
    - `ThreadPoolExecutor(max_workers)`로 처리한다.
    - 각 파일은 `normalize_image` → `image_hash`(정규화 전 원본 기준) → cache 조회 → `recognize` 순서로 처리한다.
    - `UnsupportedImageError`와 `RecognitionError`는 잡아서 `error`에 넣는다.
    - 결과는 입력 순서대로 돌려준다.
  - `build_expenses`
    - `expense_id`는 `image_hash[:12]`로 정한다. 같은 이미지를 두 번 올리면 id가 같아지므로 `-2` 같은 접미사를 붙인다.
    - 연도 보정: 연도만 여행 연도로 바꿨을 때 여행 기간 안에 들어오면 바꾸고 경고를 남긴다.
  - `sort_expenses`의 정렬 키: `(paid_at is None, paid_at.date(), time_known, paid_at.time())`
  - `find_duplicates`: 시간이 있는 건끼리만 비교한다. 결과는 `(앞 id, 뒤 id)`를 시간순으로 정렬해 돌려준다.

- [ ] **Step 5: 통과 확인 후 커밋**
  - Run: `.venv/bin/pytest -v`
  - Expected: 전부 PASS
```bash
git add core/recognize_service.py core/expense_builder.py tests/test_recognize_service.py tests/test_expense_builder.py
git commit -m "feat: 일괄 인식과 결제 건 변환·정렬·중복 탐지 추가"
```

### Task 9: 평가 지표와 실행 스크립트

**Files:**
- Create: `eval/__init__.py`, `eval/metrics.py`, `eval/run_eval.py`, `eval/ground_truth.json`(형식 예시 2건), `eval/LABELING.md`, `tests/test_eval_metrics.py`

**Interfaces:**
- Consumes: `Receipt`, `recognize_batch`, `GeminiRecognizer`, `MockRecognizer`, `get_setting`
- Produces:
  - `ground_truth.json` 항목: `{"file": "real/r01.jpg", "source": "real" | "synthetic", "kind": "food", "expected": {"doc_type", "merchant_name", "paid_at", "total_amount"}}`
  - `normalize_merchant(name: str | None) -> str`
  - `score_case(expected: dict, actual: Receipt | None) -> dict[str, bool]`: 키는 `doc_type`, `merchant_name`, `paid_at`, `total_amount`, `core3`
  - `summarize(rows: list[dict]) -> pandas.DataFrame`: `source`별 + 전체 행. 열은 필드별 정확도, `core3`, 평균 응답 시간, 오류율
  - CLI: `python -m eval.run_eval --prompt v1 [--recognizer gemini|mock] [--limit N]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@pytest.mark.parametrize("a,b", [("스타벅스 애월점", "스타벅스"), ("흑돼지 명가", "흑돼지명가"),
                                 ("(주)이마트24 제주점", "이마트24")])
def test_normalize_merchant_equivalents(a, b):
    assert normalize_merchant(a) == normalize_merchant(b)

def test_core3_requires_all_three():
    exp = {"doc_type": "receipt", "merchant_name": "스타벅스", "paid_at": "2026-10-11T15:02", "total_amount": 18000}
    s = score_case(exp, receipt(merchant="스타벅스 애월점", paid_at="2026-10-11T15:02", total=18000))
    assert s["core3"] is True
    assert score_case(exp, receipt(merchant="스타벅스", paid_at="2026-10-11T15:03", total=18000))["core3"] is False

def test_not_receipt_case_scored_on_doc_type_only():
    exp = {"doc_type": "not_receipt", "merchant_name": None, "paid_at": None, "total_amount": None}
    assert score_case(exp, receipt(doc_type="not_receipt", total=None))["core3"] is True

def test_failed_recognition_scores_false():
    assert score_case({"doc_type": "receipt", "merchant_name": "x", "paid_at": None, "total_amount": 1}, None)["core3"] is False

def test_summarize_splits_by_source():
    df = summarize([row("real", core3=True, t=2.0), row("real", core3=False, t=4.0, error="x"),
                    row("synthetic", core3=True, t=1.0)])
    real = df.loc["real"]
    assert real["core3"] == 0.5 and real["avg_seconds"] == 3.0 and real["error_rate"] == 0.5
    assert df.loc["all"]["core3"] == pytest.approx(2 / 3)
```

- [ ] **Step 2: 실패 확인 → `eval/metrics.py` 구현 → 통과 확인**
  - Run: `.venv/bin/pytest tests/test_eval_metrics.py -v`
  - `normalize_merchant`
    - `(주)`, `주식회사`, 공백, 문장부호를 제거한다.
    - 공백으로 나눈 토큰이 2개 이상이고 마지막 토큰이 `점`으로 끝나면 지점명으로 보고 제거한다. 토큰이 1개면 제거하지 않는다(예: "편의점"). 이 처리는 공백을 제거하기 전에 한다.
  - `paid_at`은 문자열 그대로 비교한다. 분 단위까지 일치해야 한다.

- [ ] **Step 3: `eval/run_eval.py` 구현**
  - `ground_truth.json`을 읽고, `eval/images/{file}`을 읽어 `recognize_batch`를 실행한다. cache는 쓰지 않는다.
  - 결과 두 가지를 저장한다.
    - 원본 결과: `eval/results/{prompt}_{YYYYmmdd-HHMM}.json`
    - 요약: `eval/results/{prompt}_{YYYYmmdd-HHMM}_summary.csv`
  - 요약 표를 출력한다. 틀린 건은 파일명, 필드, 기대값, 실제값을 목록으로 출력한다. 이 목록이 실패 분석의 재료가 된다.

- [ ] **Step 4: mock으로 끝까지 실행되는지 확인**
  - Run: `.venv/bin/python -m eval.run_eval --prompt v1 --recognizer mock`
  - Expected: 예시 2건으로 요약 표가 출력되고, `eval/results/`에 파일 2개가 생긴다.

- [ ] **Step 5: `eval/LABELING.md` 작성**
  - 라벨링 규칙: 실제 결제 금액, 상호는 간판 기준, 일시는 결제 시각, 카드번호는 가리고 촬영
  - 테스트셋 구성: 식당 8, 카페 4, 마트·편의점 3, 교통·주유 2, 숙소 캡처 3, 까다로운 경우 5
  - 파일 이름 규칙: `real/r01.jpg`, `synthetic/s01.png`

- [ ] **Step 6: 커밋**
```bash
git add eval tests/test_eval_metrics.py
git commit -m "feat: 인식 정확도 평가 지표와 실행 스크립트 추가"
```

### Task 10: 직접 만든 샘플 영수증 생성기

**Files:**
- Create: `eval/make_synthetic.py`, `eval/synthetic_specs.json`, `tests/test_make_synthetic.py`

**Interfaces:**
- Produces:
  - `render_receipt(spec: dict, font_path: str) -> PIL.Image.Image`
  - `apply_variant(img, variant: Literal["clean", "blur", "rotate", "dark"]) -> Image`
  - CLI: `python -m eval.make_synthetic --font <ttf 경로>`
    - 이미지는 `eval/images/synthetic/`에 쓴다.
    - `ground_truth.json`에는 `source="synthetic"` 항목만 추가하거나 갱신한다. 실물 항목은 건드리지 않는다.
  - spec 형식: `{"id": "s01", "kind": "cafe", "merchant": "...", "address": "...", "paid_at": "...", "items": [...], "discount": 0, "variant": "blur"}`. 실제 결제 금액은 `items 합 − discount`로 계산한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_expected_amount_applies_discount():
    assert expected_total({"items": [{"name": "a", "amount": 5000}, {"name": "b", "amount": 3000}],
                           "discount": 1000}) == 7000

def test_render_produces_portrait_image(korean_font):
    img = render_receipt(SPEC, korean_font)
    assert img.height > img.width

def test_regenerate_keeps_real_entries(tmp_path, korean_font):
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps([{"file": "real/r01.jpg", "source": "real", "kind": "food", "expected": {}}]))
    generate([SPEC], korean_font, tmp_path / "img", gt)
    files = [e["file"] for e in json.loads(gt.read_text())]
    assert "real/r01.jpg" in files and "synthetic/s01.png" in files
```
  - `korean_font` fixture는 macOS 기본 한글 폰트(`/System/Library/Fonts/AppleSDGothicNeo.ttc`)를 찾는다. 없으면 `pytest.skip`한다.

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**
  - Run: `.venv/bin/pytest tests/test_make_synthetic.py -v`
  - `apply_variant`
    - blur: `GaussianBlur(1.5)`
    - rotate: 7도 회전, 흰 배경
    - dark: 밝기 0.6

- [ ] **Step 3: 샘플 spec 13개 작성 후 생성**
  - 구성:
    - 숙소 예약 캡처 3개: 앱 화면 스타일, 날짜만 있음
    - 할인·포인트 2개
    - 흐림 1개, 기울어짐 1개
    - 카페 2개, 마트 2개, 교통 2개
  - Run: `.venv/bin/python -m eval.make_synthetic --font /System/Library/Fonts/AppleSDGothicNeo.ttc`
  - Expected: `eval/images/synthetic/`에 13장이 생기고, ground_truth에 synthetic 항목 13개가 들어간다.

- [ ] **Step 4: 커밋 후 머지**
```bash
git add eval/make_synthetic.py eval/synthetic_specs.json eval/images/synthetic eval/ground_truth.json tests/test_make_synthetic.py
git commit -m "feat: 평가용 샘플 영수증 생성기 추가"
```
  - `feature/recognizer`를 main에 머지한다.

---

## 단계 2 — `feature/ui`

UI 테스트는 `streamlit.testing.v1.AppTest`를 쓴다. 테스트에서는 `RECOGNIZER=mock`, `APP_PASSWORD`를 빈 값으로 설정한다.

### Task 11: 앱 골격, 상태 관리, 비밀번호, 여행 설정 단계

**Files:**
- Create: `app.py`, `ui/__init__.py`, `ui/state.py`, `ui/setup_step.py`, `tests/test_state.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `Trip`, `PayoutInfo`, `get_setting`
- Produces:
  - `ui/state.py`
    - `STEPS = ["설정", "업로드", "검토", "정산"]`
    - `get_trip() -> Trip | None`, `set_trip(trip: Trip) -> None`
    - `sync_members(trip: Trip, members: list[str], leader: str) -> Trip`: 빠진 사람을 각 결제 건 participants에서 제거한다. payer가 빠진 사람이면 leader로 바꾼다.
    - `get_recognizer() -> Recognizer`: `RECOGNIZER` 설정에 따라 Mock 또는 Gemini를 고른다. 키가 없으면 `RecognitionError`를 던진다.
  - `ui/setup_step.py`: `render_setup() -> None`
  - `app.py`: `check_password() -> bool`, 단계 네비게이션

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_state.py — Review Focus 2
def test_sync_members_removes_dropped_member_everywhere():
    t = trip_with([exp(9000, "C", ["A", "B", "C"])])
    t2 = sync_members(t, ["A", "B"], leader="A")
    assert t2.members == ["A", "B"] and t2.expenses[0].participants == ["A", "B"] and t2.expenses[0].payer == "A"

def test_sync_members_keeps_fund_wallet_payer():
    t = trip_with([exp(9000, FUND_WALLET, ["A", "B", "C"])], mode="fund", fee=10000)
    assert sync_members(t, ["A", "B"], leader="A").expenses[0].payer == FUND_WALLET

# tests/test_app.py
def test_password_gate_blocks(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    at = AppTest.from_file("app.py").run()
    assert at.text_input[0].label == "데모 비밀번호" and not at.button(key="setup_save")

def test_setup_rejects_duplicate_members(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 민수")
    at.button(key="setup_save").click().run()
    assert "중복" in at.error[0].value

def test_setup_saves_trip(monkeypatch):
    at = open_app(monkeypatch)
    fill_setup(at, members="민수, 지영, 철수")
    at.button(key="setup_save").click().run()
    assert at.session_state["trip"].members == ["민수", "지영", "철수"]
```

- [ ] **Step 2: 실패 확인**
  - Run: `.venv/bin/pytest tests/test_state.py tests/test_app.py -v`
  - Expected: FAIL

- [ ] **Step 3: 구현**
  - `check_password`
    - `APP_PASSWORD`가 비어 있으면 통과시킨다(로컬).
    - 아니면 `st.text_input("데모 비밀번호", type="password")`로 받는다.
  - 설정 단계 입력
    - 여행 이름, 날짜 2개
    - 참석자: 쉼표로 구분하는 `text_input`
    - 대표: `selectbox`
    - 방식: `radio`(선결제형/회비형). 회비형을 고르면 1인 회비를 입력받는다.
    - 사람별 송금 정보: `expander` 안에 계좌, 토스, 카카오페이 입력
  - 저장 버튼을 누르면 `Trip(...)`을 만든다. `ValidationError`가 나면 오류 메시지를 `st.error`로 보여 준다.
  - 이미 여행이 있으면 `sync_members`로 갱신한다.
  - 단계 이동은 `st.session_state["step"]`과 사이드바 `radio`로 한다. 앞 단계를 끝내지 않았으면 뒤 단계를 비활성 안내로 대신한다.
  - 사이드바에 현재 인식기(mock/gemini)를 표시한다.

- [ ] **Step 4: 통과 확인 및 화면 확인**
  - Run: `.venv/bin/pytest -v`
  - Run: `streamlit run app.py`를 실행하고 Orca 내장 브라우저로 설정 단계를 직접 확인한다.

- [ ] **Step 5: 커밋**
```bash
git add app.py ui tests/test_state.py tests/test_app.py
git commit -m "feat: 앱 골격·비밀번호·여행 설정 단계 추가"
```

### Task 12: 업로드 단계

**Files:**
- Create: `ui/upload_step.py`
- Modify: `app.py`(단계 연결), `tests/test_app.py`

**Interfaces:**
- Consumes: `recognize_batch`, `MAX_FILES`, `build_expenses`, `sort_expenses`, `get_recognizer`, `get_trip`/`set_trip`
- Produces:
  - `render_upload() -> None`
  - 세션 키: `"recognition_cache": dict[str, Receipt]`, `"upload_notices": list[str]`

- [ ] **Step 1: 실패하는 테스트 작성**
  - `AppTest`는 파일 업로더를 직접 다루기 어렵다. 그래서 업로드 처리를 `process_uploads(files: list[tuple[str, bytes]]) -> None` 함수로 분리하고, 이 함수를 테스트한다.

```python
def test_process_uploads_adds_sorted_expenses(monkeypatch, app_session):
    process_uploads([("a.png", png()), ("b.png", png(color="red"))])
    trip = app_session["trip"]
    assert trip.expenses == sort_expenses(trip.expenses) and len(trip.expenses) >= 1

def test_process_uploads_appends_not_replaces(app_session):
    process_uploads([("a.png", png())]); n = len(app_session["trip"].expenses)
    process_uploads([("c.png", png(color="blue"))])
    assert len(app_session["trip"].expenses) >= n

def test_process_uploads_over_limit_shows_notice(app_session):
    process_uploads([("a.png", png())] * 31)
    assert any("30" in n for n in app_session["upload_notices"])
```
  - `app_session` fixture는 `st.session_state`를 dict로 바꿔 끼운다. 이 fixture를 쓰려면 `ui/state.py`가 세션에 접근하는 함수 하나를 거치도록 만들어야 한다. 그 함수를 monkeypatch한다.

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**
  - 업로더: `st.file_uploader(accept_multiple_files=True, type=["jpg", "jpeg", "png", "heic"])`
  - 업로더 위에 안내 문구를 둔다: "이미지는 Google Gemini API로 전송됩니다. 카드번호·이름은 가리고 올려 주세요."
  - "인식 시작" 버튼을 누르면 `st.progress`와 `on_progress`로 진행률을 보여 준다.
  - 인식 결과의 안내 메시지는 `st.warning`으로 나열한다.
  - `RecognitionError`(키 없음)가 나면 `st.error`로 안내하고, "수동으로 추가하기"로 넘어가게 한다.
  - Run: `.venv/bin/pytest -v`

- [ ] **Step 3: 커밋**
```bash
git add ui/upload_step.py app.py tests/test_app.py
git commit -m "feat: 영수증 일괄 업로드와 인식 단계 추가"
```

### Task 13: 검토·참석자 체크 단계

**Files:**
- Create: `ui/review_step.py`
- Modify: `app.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `find_duplicates`, `sort_expenses`, `Expense`, `FUND_WALLET`
- Produces:
  - `render_review() -> None`
  - `add_manual_expense(trip: Trip, merchant: str, amount: int, paid_at: datetime | None) -> Trip`: source `"manual"`, payer는 기본값(leader 또는 지갑), participants는 전원

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_add_manual_expense_defaults():
    t = add_manual_expense(prepaid_trip, "주차비", 4000, None)
    e = t.expenses[-1]
    assert (e.source, e.payer, e.participants, e.amount) == ("manual", "A", ["A", "B", "C"], 4000)

def test_review_unchecking_member_updates_participants(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(18000, "A", ["A", "B", "C"], id="cafe")])
    at.checkbox(key="part_cafe_C").uncheck().run()
    assert at.session_state["trip"].expenses[0].participants == ["A", "B"]

def test_review_shows_duplicate_warning(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[dup_a, dup_b])
    assert any("중복" in w.value for w in at.warning)
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**
  - 결제 건마다 `st.container(border=True)`로 카드를 만든다.
    - 상호, 일시(`date_input` + `time_input`, 시간 모름 체크), 주소, 금액(`number_input`)
    - 결제자: `selectbox`. 회비형이면 선택지에 `FUND_WALLET`을 넣는다.
    - 참석자: 사람마다 `checkbox(key=f"part_{expense_id}_{name}")`
    - 정산 제외: `checkbox(key=f"excl_{expense_id}")`
    - 그 건의 `warnings`는 노란 안내로 표시한다.
  - 중복 쌍은 위쪽에 `st.warning`으로 모아서 보여 준다.
  - "수동 추가" 폼을 둔다.
  - 수정한 값은 위젯 변경 즉시 `Expense.model_copy(update=...)`로 반영한다.
  - Run: `.venv/bin/pytest -v`

- [ ] **Step 3: 커밋**
```bash
git add ui/review_step.py app.py tests/test_app.py
git commit -m "feat: 결제 건 검토·참석자 체크·수동 추가 단계 추가"
```

### Task 14: 정산 결과 단계와 JSON 내보내기/불러오기

**Files:**
- Create: `ui/result_step.py`
- Modify: `app.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `readiness_errors`, `compute_balances`, `plan_transfers`, `build_message`, `format_won`, `Trip`
- Produces:
  - `render_result() -> None`
  - `export_trip(trip: Trip) -> bytes`
  - `import_trip(data: bytes) -> Trip`: 실패하면 `ValueError("불러올 수 없는 파일입니다")`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_export_import_roundtrip():
    t = prepaid_trip_with_expenses()
    assert import_trip(export_trip(t)) == t

@pytest.mark.parametrize("data", [b"", b"{}", b"not json", b'{"name": 1}'])
def test_import_rejects_bad_file(data):
    with pytest.raises(ValueError, match="불러올 수 없는"):
        import_trip(data)

def test_result_blocked_when_not_ready(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(0, "A", ["A"])], step="정산")
    assert any("금액이 0원" in e.value for e in at.error) and not at.dataframe

def test_result_shows_table_and_messages(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(30000, "A", ["A", "B", "C"])], step="정산")
    assert at.dataframe and sum("10,000원" in c.value for c in at.code) == 2
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**
  - `readiness_errors`가 있으면 오류를 `st.error`로 나열하고, "검토로 돌아가기" 버튼만 보여 준다.
  - 정산 표 열: 이름, 낸 돈, 부담액, 차액. 금액은 `format_won`으로 표시한다.
  - 송금마다 `st.code(build_message(...), language=None)`를 쓴다. 이 블록에 복사 버튼이 기본으로 있다.
  - JSON 내려받기는 `st.download_button`을 쓴다. 불러오기는 설정 단계 상단에 `file_uploader(type=["json"])`로 둔다.
  - Run: `.venv/bin/pytest -v`

- [ ] **Step 3: 끝까지 수동 확인**
  - mock 모드에서 확인한다: 설정 → 업로드 5장 → 카페 1건에서 1명 해제 → 결제자 1건 변경 → 정산 → 메시지 복사 → JSON 내려받기 → 새로고침 → 불러오기 → 같은 결과

- [ ] **Step 4: 커밋**
```bash
git add ui/result_step.py app.py tests/test_app.py
git commit -m "feat: 정산 결과·송금 메시지·JSON 내보내기 단계 추가"
```

### Task 15: 배포와 README 실행 방법

**Files:**
- Create: `README.md`, `docs/ai-log.md`(틀)
- Modify: 없음

- [ ] **Step 1: GitHub 저장소 연결 (사람이 함께)**
  - 저장소 이름과 공개 여부를 정한 뒤 `git remote add origin ...`, `git push -u origin main`

- [ ] **Step 2: README 작성**
  - 소개 한 줄
  - 실행 방법: clone → `./scripts/setup_worktree.sh` → `.env`에 키 입력 → `streamlit run app.py`
  - mock 모드 실행: `RECOGNIZER=mock`
  - 평가 실행 명령
  - 키 발급 링크(Gemini, 카카오)
  - 무료 등급 데이터 정책 확인 결과
  - 한계

- [ ] **Step 3: Streamlit Community Cloud 배포 (사람이 함께)**
  - main 브랜치, `app.py`, Python 3.12
  - Secrets: `GEMINI_API_KEY`, `GEMINI_MODEL`, `APP_PASSWORD`, `RECOGNIZER="gemini"`

- [ ] **Step 4: 배포 확인**
  - 배포 URL에서 비밀번호 화면 → 실제 영수증 3장 인식 → 정산까지 동작하는지 확인한다.
  - Expected: 오류 없이 송금 메시지가 나온다.

- [ ] **Step 5: 커밋 후 머지**
```bash
git add README.md docs/ai-log.md
git commit -m "docs: README 실행·배포 방법 추가"
```

---

## 단계 3A — `feature/prompt-v2`

### Task 16: v1 측정 → 실패 분석 → v2 → 비교

**Files:**
- Create: `prompts/v2.md`, `eval/results/v1_*_summary.csv`, `eval/results/v2_*_summary.csv`, `docs/eval-report.md`
- Modify: `docs/ai-log.md`

- [ ] **Step 1: 테스트셋 준비 확인**
  - `eval/ground_truth.json`에 real 12건 이상, synthetic 13건 이하, 합계 25건이 있어야 한다.
  - 실물 이미지는 `eval/images/real/`에 둔다(커밋 안 함).

- [ ] **Step 2: v1 측정**
  - Run: `.venv/bin/python -m eval.run_eval --prompt v1 --recognizer gemini`
  - Expected: 요약 표와 틀린 건 목록이 나온다.

- [ ] **Step 3: 실패 분석**
  - 틀린 건을 원인별로 묶어 `docs/eval-report.md`에 표로 적는다.
  - 원인 예시: 합계와 결제금액을 혼동, 지점명, 날짜 형식, 예약 캡처 금액(1박/총액), 흐림

- [ ] **Step 4: `prompts/v2.md` 작성**
  - 원인 하나당 규칙 하나를 추가한다(예: "받을 금액/결제 금액 줄을 우선한다").
  - 규칙마다 어떤 실패에서 나왔는지 `docs/ai-log.md`에 기록한다.

- [ ] **Step 5: v2 측정과 비교**
  - Run: `.venv/bin/python -m eval.run_eval --prompt v2 --recognizer gemini`
  - `docs/eval-report.md`에 v1과 v2의 core3·필드별 정확도·응답 시간·오류율을 real과 synthetic으로 나눈 표로 정리한다.
  - 나빠진 항목이 있으면 그 이유도 적는다.

- [ ] **Step 6: 앱 기본 프롬프트를 더 나은 버전으로 설정**
  - `ui/state.py`의 기본 버전을 고른다. 사이드바에서도 바꿀 수 있게 한다.

- [ ] **Step 7: 커밋 후 머지**
```bash
git add prompts/v2.md eval/results/*_summary.csv docs/eval-report.md docs/ai-log.md ui/state.py
git commit -m "feat: 실패 분석 기반 프롬프트 v2와 평가 리포트 추가"
```

---

## 단계 3B — `feature/map` (선택)

### Task 17: 카카오 좌표 변환 (`core/geocode.py`)

**Files:**
- Create: `core/geocode.py`, `tests/test_geocode.py`

**Interfaces:**
- Consumes: `Expense`
- Produces:
  - `geocode(expense: Expense, api_key: str, session: requests.Session | None = None) -> tuple[float, float] | None`: 반환은 `(lat, lng)`

- [ ] **Step 1: 실패하는 테스트 작성**
  - 가짜 session을 써서 URL별로 응답을 정해 둔다.

```python
def test_uses_address_search_first():
    s = fake_session({"address.json": {"documents": [{"x": "126.3", "y": "33.4"}]}})
    assert geocode(mk(address="제주 제주시 애월읍 1"), "k", s) == (33.4, 126.3)

def test_falls_back_to_keyword_search():
    s = fake_session({"address.json": {"documents": []}, "keyword.json": {"documents": [{"x": "126.5", "y": "33.5"}]}})
    assert geocode(mk(address="이상한 주소", merchant="스타벅스 애월점"), "k", s) == (33.5, 126.5)

def test_returns_none_on_http_error_or_no_result():
    assert geocode(mk(address=None, merchant="없는가게"), "k", fake_session({"keyword.json": {"documents": []}})) is None
    assert geocode(mk(address="x"), "k", failing_session(500)) is None

def test_sends_kakao_auth_header():
    s = fake_session({"address.json": {"documents": [{"x": "1", "y": "2"}]}})
    geocode(mk(address="x"), "abc", s)
    assert s.last_headers["Authorization"] == "KakaoAK abc"
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**
  - 주소 검색: `https://dapi.kakao.com/v2/local/search/address.json?query=`
  - 키워드 검색: `https://dapi.kakao.com/v2/local/search/keyword.json?query=`
  - `timeout=5`를 준다. `requests.RequestException`과 4xx/5xx는 `None`으로 처리한다.
  - Run: `.venv/bin/pytest tests/test_geocode.py -v`

- [ ] **Step 3: 커밋**
```bash
git add core/geocode.py tests/test_geocode.py
git commit -m "feat: 카카오 로컬 API 좌표 변환 추가"
```

### Task 18: 경로 지도 화면

**Files:**
- Create: `ui/map_view.py`
- Modify: `ui/result_step.py`(정산 결과 아래 지도 섹션), `tests/test_app.py`

**Interfaces:**
- Consumes: `geocode`, `sort_expenses`, `get_setting`
- Produces:
  - `build_route_map(points: list[tuple[str, float, float]]) -> folium.Map`: 이름, lat, lng를 시간순으로 받는다
  - `render_map(trip: Trip) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_route_map_has_antpath_and_numbered_markers():
    m = build_route_map([("흑돼지", 33.4, 126.3), ("카페", 33.5, 126.5)])
    html = m.get_root().render()
    assert "antPath" in html and "1. 흑돼지" in html and "2. 카페" in html

def test_render_map_without_key_shows_info(monkeypatch):
    at = open_app_with_trip(monkeypatch, expenses=[exp(1000, "A", ["A"])], step="정산", kakao_key="")
    assert any("카카오" in i.value for i in at.info)
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인**
  - 좌표는 `st.session_state["geo_cache"]`에 expense_id를 키로 캐시한다.
  - excluded가 아닌 결제 건만 시간순으로 이어 그린다.
  - 좌표를 찾지 못한 건은 지도 아래에 "위치를 찾지 못한 결제: ..."로 나열한다.
  - `st_folium(m, height=450)`로 표시한다.
  - Run: `.venv/bin/pytest -v`

- [ ] **Step 3: 화면 확인 후 커밋·머지**
  - 실제 제주 주소 3곳 이상으로 경로가 움직이는지 내장 브라우저에서 확인한다.
```bash
git add ui/map_view.py ui/result_step.py tests/test_app.py
git commit -m "feat: 여행 경로 지도 추가"
```

---

## 단계 4 — `feature/hardening`

### Task 19: 상호 테스트 반영과 마무리 문서

**Files:**
- Modify: 상호 테스트에서 문제가 나온 파일, `README.md`, `docs/ai-log.md`
- Create: `docs/stability.md`

- [ ] **Step 1: 방어 시연 체크리스트 작성과 직접 확인** — `docs/stability.md`
  - 각 항목은 입력, 기대 화면, 확인 결과로 기록한다.
  - 영수증이 아닌 사진 → 제외 안내
  - API 키 없음 → 오류 안내 + 수동 추가 경로
  - 업로드 0장 / 31장 → 안내
  - 참석자 전원 해제 → 정산 차단
  - 중복 업로드 → 경고
  - PDF 업로드 → "이미지 파일이 아닙니다"
  - 잘못된 JSON 불러오기 → 안내

- [ ] **Step 2: 상호 테스트(리뷰 그룹 3~5명)**
  - 이상 입력과 소요 시간을 `docs/stability.md`에 기록한다.
  - 발견한 문제마다 실패 테스트를 먼저 쓰고 고친다.

- [ ] **Step 3: 전체 검증**
  - Run: `.venv/bin/pytest -v && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
  - Expected: 전부 PASS, 린트 오류 0
  - 배포 URL에서 Step 1 체크리스트를 다시 확인한다.

- [ ] **Step 4: 문서 마무리**
  - README에 평가 결과 요약과 한계를 넣는다.
  - `docs/ai-log.md`에 프롬프트 변경, CLAUDE.md 활용, AI 실수 수정 사례를 정리한다.

- [ ] **Step 5: 커밋 후 머지**
```bash
git add -A
git commit -m "fix: 상호 테스트 결과 반영과 안정성 문서 추가"
```
