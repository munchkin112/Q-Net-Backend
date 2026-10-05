# AGENTS.md

## 현재 사용자 확정사항 (2026-10-05)

- 데이터베이스: Render PostgreSQL. Supabase 전용 기능을 도입하지 않는다.
- 보유 자격과 경력 날짜는 필요할 때만 추가 입력받는다.
- schedules는 종목·회차·단계별 행과 날짜 기간으로 저장한다.
- D05 응시조건 JSONB/reviewed 비교, D08 Calendar 구현은 보류한다.
- 북마크 테이블 SQL과 코드는 주석 상태로 준비하고 지금 활성화하지 않는다.
- 로드맵 및 관련 테이블·API·로직은 현재 작업에서 제외한다.
- 아래 일반 규칙과 충돌하면 사용자 추가 결정이 우선한다.
- 코드 난이도는 사용자가 공유한 2026-aio2-guide 수업의 Python 함수·조건문·반복문·Pydantic·httpx·FastAPI 수준을 기준으로 한다. 필수적인 SQL/XML 처리에는 한국어 설명을 붙이고 불필요한 추상화를 피한다.
- 독스트링과 설명 주석은 한국어로 작성한다. 함수·변수명은 영어를 유지한다.

## 1. Project Priority

이 프로젝트의 최우선 기준은 `PRD.md`다.

코드를 작성하거나 수정하기 전에 반드시 `PRD.md`의 요구사항과 범위를 먼저 확인한다.

우선순위는 다음과 같다.

1. `PRD.md`의 제품 요구사항
2. 현재 프로젝트의 기존 코드 구조
3. 이 `AGENTS.md`의 구현 규칙
4. 일반적인 개발 관례

PRD와 구현 아이디어가 충돌하면 PRD를 우선한다.

PRD에 명시되지 않은 기능을 임의로 핵심 기능에 추가하지 않는다.

---

# 2. Project Overview

프로젝트명:

Q-Net 국가자격 시험·응시 준비 일정 코디네이터

핵심 목표:

사용자의 학력, 전공, 경력, 희망 직무를 기반으로 응시 가능한 국가자격증을 탐색하고, 공식 정보를 근거로 응시자격과 시험정보를 제공하며, 주요 시험 일정을 Google Calendar에 등록한다.

기본 흐름:

```text
Google 로그인
→ 프로필 입력
→ 프로필 충분성 확인
→ 자격증 후보 탐색
→ 자격증 선택
→ 응시자격 확인
→ 자격증 상세정보 조회
→ 시험회차 선택
→ 필요 시 시험 준비 로드맵 생성
→ 결과 검증
→ Google Calendar 등록
→ 최종 응답
```

---

# 3. Core Development Principle

이 프로젝트에서 중요한 것은 복잡한 Agent 구조를 만드는 것이 아니다.

다음 흐름이 코드에서 명확하게 보여야 한다.

```text
사용자 입력
→ LLM 판단
→ Tool 선택
→ Tool 실행
→ Tool 결과 반환
→ State 갱신
→ 결과 검증
→ Router 분기
→ Retry / Fallback
→ 최종 응답
```

사용자가 학습 중인 코드를 읽고 직접 수정할 수 있도록 구현한다.

불필요하게 복잡한 구조, 과도한 추상화, 디자인 패턴을 사용하지 않는다.

---

# 4. Tech Stack

프로젝트의 기본 기술 스택은 다음을 기준으로 한다.

- Python
- FastAPI
- LangChain
- LangGraph
- Tool Calling
- RAG
- PostgreSQL
- Google OAuth
- Google Calendar API
- 외부 Q-Net / 공공데이터 API

기존 프로젝트에서 이미 선택된 라이브러리나 구조가 있다면 이를 우선 유지한다.

---

# 5. LangChain Tool Calling Rules

Tool Calling은 다음 개념을 명확하게 구분한다.

## `@tool`

일반 Python 함수를 LLM이 사용할 수 있는 Tool로 정의한다.

```python
@tool
def get_exam_schedule(...):
    ...
```

## `bind_tools()`

LLM에게 사용할 수 있는 Tool 목록을 알려준다.

```python
llm_with_tools = llm.bind_tools(tools)
```

## `tool_calls`

LLM이 어떤 Tool을 사용할지 판단한 결과다.

```python
ai_message.tool_calls
```

## `tool.invoke()`

LLM이 Tool을 직접 실행하는 것이 아니다.

Python 프로그램이 Tool Call을 확인한 후 실제 Tool을 실행한다.

```python
result = tool.invoke(tool_call["args"])
```

## `ToolMessage`

Tool 실행 결과를 다시 LLM에게 전달한다.

```python
ToolMessage(
    content=str(result),
    tool_call_id=tool_call["id"],
)
```

다음 흐름을 혼동하지 않는다.

```text
LLM
→ Tool 선택

Python 코드
→ Tool 실행

ToolMessage
→ 결과를 LLM에 전달
```

---

# 6. Tool Design Rules

Tool은 실제 작업을 담당한다.

주요 역할:

- Q-Net API 조회
- 공공 API 조회
- DB 조회
- 공식 문서 RAG 검색
- Google Calendar 이벤트 생성
- 외부 서비스 호출

예상 Tool:

```python
@tool
def search_certificates(...):
    """사용자 조건과 관련된 국가자격증 후보를 조회한다."""
```

```python
@tool
def get_certificate_eligibility(...):
    """선택한 자격증의 공식 응시자격 정보를 조회한다."""
```

```python
@tool
def get_exam_schedule(...):
    """자격증 시험일정을 조회한다."""
```

```python
@tool
def get_exam_information(...):
    """시험과목, 합격기준, 응시료 정보를 조회한다."""
```

```python
@tool
def search_official_document(...):
    """공식 문서를 대상으로 RAG 검색을 수행한다."""
```

```python
@tool
def create_calendar_event(...):
    """Google Calendar 이벤트를 생성한다."""
```

Tool 내부에서 또 다른 LLM 판단을 불필요하게 수행하지 않는다.

Tool은 가능한 한 입력 → 실제 작업 → 결과 반환 구조를 유지한다.

---

# 7. LangGraph Rules

LangGraph에서는 다음 요소를 명확하게 구분한다.

- State: 현재 작업 상태
- Node: 하나의 작업 단위
- Edge: Node 간 이동
- Conditional Edge: 조건에 따른 분기
- Router: 다음 Node를 결정하는 함수

기본 Graph 흐름은 PRD의 서비스 흐름을 우선한다.

```text
START
→ profile_check
→ certificate_search
→ eligibility_check
→ certificate_detail
→ schedule_select
→ roadmap_generate
→ validate_result
→ calendar_register
→ final_response
→ END
```

단, 모든 사용자가 모든 Node를 거쳐야 하는 것은 아니다.

조건에 따라 분기한다.

예:

```text
profile_check
├─ 정보 충분
│   → certificate_search
│
└─ 정보 부족
    → ask_profile_info
```

```text
eligibility_check
├─ 응시 가능성 높음
│   → certificate_detail
│
├─ 추가 정보 필요
│   → ask_additional_info
│
└─ 미충족 가능성
    → alternative_certificate
```

```text
validate_result
├─ 정상
│   → 다음 단계
│
└─ 오류
    → repair_router
```

---

# 8. State Rules

State에는 현재 Graph에서 실제로 필요한 데이터만 저장한다.

처음부터 지나치게 큰 State를 만들지 않는다.

예:

```python
from typing import TypedDict


class AgentState(TypedDict):
    user_id: int
    user_message: str

    profile: dict
    missing_profile_fields: list[str]

    certificate_candidates: list[dict]
    selected_certificate: dict | None

    eligibility_result: dict | None
    certificate_detail: dict | None

    schedules: list[dict]
    selected_schedule: dict | None

    validation_errors: list[dict]
    retry_count: int

    calendar_result: dict | None

    final_answer: str
```

기능이 실제로 추가될 때 State도 함께 확장한다.

사용하지 않는 필드를 미리 대량으로 만들지 않는다.

---

# 9. Node Rules

Node 하나는 가능한 한 하나의 책임만 가진다.

좋은 예:

```python
def profile_check(state: AgentState):
    ...
```

```python
def certificate_search(state: AgentState):
    ...
```

```python
def eligibility_check(state: AgentState):
    ...
```

```python
def validate_result(state: AgentState):
    ...
```

하나의 Node에서 다음 모든 작업을 동시에 처리하지 않는다.

```text
프로필 검사
+ 자격증 검색
+ 응시자격 판단
+ 시험일정 조회
+ Calendar 등록
```

Node는 필요한 State를 읽고 변경할 값만 반환하는 방식을 우선한다.

```python
def profile_check(state: AgentState):
    profile = state["profile"]

    missing_fields = []

    if not profile.get("education_level"):
        missing_fields.append("education_level")

    if not profile.get("desired_job"):
        missing_fields.append("desired_job")

    return {
        "missing_profile_fields": missing_fields
    }
```

---

# 10. Router Rules

단순한 조건은 LLM이 아니라 Python 코드로 판단한다.

LLM이 필요 없는 예:

- 값 존재 여부
- 숫자 비교
- 날짜 비교
- Boolean 판단
- 리스트가 비어 있는지 확인
- 중복 여부
- retry_count 비교

예:

```python
def route_profile(state: AgentState):
    if state["missing_profile_fields"]:
        return "ask_profile_info"

    return "certificate_search"
```

다음과 같은 판단을 LLM에게 맡기지 않는다.

```text
registration_end > exam_date 인가?
```

Python으로 직접 검사한다.

---

# 11. Profile Rules

PRD의 사용자 프로필 구조를 따른다.

주요 정보:

- education_level
- major
- career_history
- career_years
- desired_job
- current_status
- location
- target_date
- available_hours

프로필 정보는 최초 입력 후 DB에 저장한다.

자격증 응시자격 확인 과정에서 동일한 정보를 반복 질문하지 않는다.

저장된 프로필을 재사용한다.

추가 정보가 필요한 경우에만 추가 질문한다.

예:

```text
제조업 경력 있음
```

만으로 부족하고 실제 직무가 필요한 경우:

```text
제조업에서 담당한 구체적인 직무와 근무기간을 알려주세요.
```

---

# 12. Certificate Recommendation Rules

자격증 추천을 LLM의 주관적 판단만으로 수행하지 않는다.

기본 흐름:

```text
프로필 확인
→ 공식 응시요건 기반 필터링
→ career_tags 비교
→ 향후 시험 일정 확인
→ 후보 정렬
→ LLM이 추천 이유 설명
```

추천 후보 판단 기준은 PRD를 따른다.

우선순위:

1. 응시 가능성
2. 희망 직무 연관성
3. 학력·경력 적합성
4. 향후 시험 일정 존재 여부
5. 공식 정보 확보 여부

희망 직무 연관성은 사전에 정의된 `career_tags`를 우선 사용한다.

LLM은 추천 이유를 설명할 수 있지만 공식 응시요건을 새로 만들어서는 안 된다.

---

# 13. Eligibility Rules

응시자격 판단은 다음 두 데이터를 분리해서 사용한다.

```text
사용자 프로필
+
선택한 자격증 공식 응시요건
↓
비교
↓
응시 가능성 판단
```

판단 상태는 가능하면 제한된 값으로 관리한다.

예:

```python
from typing import Literal


EligibilityStatus = Literal[
    "eligible",
    "needs_more_info",
    "possibly_ineligible",
    "unknown",
]
```

응시자격 결과는 최소한 다음 정보를 포함하도록 한다.

```python
{
    "status": "eligible",
    "reasons": [],
    "missing_fields": [],
    "source_url": "...",
}
```

정보가 불충분한 경우 확정적으로 "응시 가능" 또는 "응시 불가"라고 표현하지 않는다.

---

# 14. Official Source Rules

핵심 정보는 공식 출처를 기준으로 한다.

우선순위:

```text
Q-Net / 공공 API
→ 내부 DB
→ 공식 문서 RAG
→ 공식 페이지
→ 확인 필요 안내
```

비공식 블로그, 커뮤니티, 개인 게시글은 다음 핵심 판정 근거로 사용하지 않는다.

- 응시자격
- 시험일
- 시험과목
- 합격기준
- 응시료

최종 결과에는 가능한 경우 공식 출처를 포함한다.

---

# 15. RAG Rules

RAG는 API에 없는 공식 문서 정보를 보완할 때 사용한다.

주요 대상:

- 세부 응시자격
- 관련 학과
- 경력 인정범위
- 출제기준
- 공식 PDF
- 공식 안내문

RAG 결과는 가능한 경우 다음 메타데이터를 포함한다.

```python
{
    "content": "...",
    "source_url": "...",
    "document_title": "...",
    "retrieved_at": "...",
}
```

검색 결과가 충분하지 않으면 정보를 만들어내지 않는다.

`unknown`, `needs_more_info`, `확인 필요` 상태를 사용할 수 있다.

---

# 16. Exam Information Rules

PRD 기준 MVP에서 제공할 정보:

- 자격증 기본정보
- 응시자격
- 관련 학과 및 경력
- 시험일정
- 시험과목
- 합격기준
- 응시료
- 시험장
- 공식 출처

이번 MVP에서 기본적으로 제외하는 정보:

- 합격률
- 응시자 통계
- 합격자 통계

PRD 범위를 벗어나 통계 기능을 임의로 핵심 기능에 추가하지 않는다.

---

# 17. Schedule Validation Rules

시험일정은 반드시 검증한다.

최소 검증:

```text
접수 시작일 <= 접수 종료일
접수 종료일 <= 시험일
시험일 <= 합격발표일
```

추가 검증:

- 필수 날짜 누락
- 선택한 회차와 자격증 불일치
- 과거 시험을 미래 일정처럼 표시
- 공식 출처 없음
- 날짜 형식 오류
- Calendar 중복 등록

단순 날짜 검증은 LLM이 아니라 Python 코드로 수행한다.

---

# 18. Validation and Self-Reflection Rules

PRD의 `FR-07 결과 검증 및 자가성찰`을 반드시 구현한다.

자가성찰을 LLM의 긴 사고 과정 출력으로 구현하지 않는다.

오류를 구조화된 상태로 관리한다.

예:

```python
{
    "error_type": "schedule_inconsistency",
    "cause": "접수 종료일이 시험일보다 늦음",
    "repair_action": "retry_schedule_api",
    "retry_count": 1,
}
```

기본 흐름:

```text
결과 생성
→ validate_result
→ 오류 확인

오류 없음
→ 다음 단계

오류 있음
→ 오류 유형 분류
→ Retry / 추가 질문 / Fallback
→ 재실행
→ 재검증
```

---

# 19. Retry Rules

Retry는 프롬프트만으로 제어하지 않는다.

Python 코드에서도 반드시 횟수를 제한한다.

예:

```python
MAX_RETRY = 1
```

```python
if state["retry_count"] < MAX_RETRY:
    ...
```

다음을 구분한다.

```text
API / Tool 실행 실패
→ Retry 가능

정보가 원래 존재하지 않음
→ 동일 요청 반복하지 않음

필수 사용자 정보 부족
→ 사용자에게 추가 질문

공식 정보 불충분
→ RAG 또는 공식 페이지 Fallback
```

무한 반복이 발생하지 않도록 한다.

---

# 20. Fallback Rules

외부 API 실패 때문에 전체 서비스가 중단되지 않도록 한다.

기본 Fallback 순서:

```text
Q-Net / 공공 API
↓ 실패
1회 Retry
↓ 실패
내부 DB
↓ 없음
공식 문서 RAG
↓ 부족
공식 페이지 안내
↓
확인 필요
```

Fallback 사용 여부를 결과에 기록할 수 있다.

예:

```python
{
    "source_type": "rag",
    "fallback_used": True,
}
```

---

# 21. Google Calendar Rules

Google Calendar 등록 대상은 PRD를 따른다.

- 원서접수 기간
- 필기시험일
- 실기시험일
- 합격발표일

사용자 권한 동의를 받은 후 생성한다.

Calendar 등록 전에 내부 DB에서 중복 여부를 확인한다.

중복 판단 기준 예:

```text
user_id
+ certificate_id
+ schedule_id
+ event_type
```

이미 `google_event_id`가 존재하면 새로운 이벤트를 생성하지 않는다.

Calendar 등록 성공 후 DB에 저장한다.

주요 필드:

- user_id
- certificate_id
- schedule_id
- event_type
- google_event_id
- starts_at
- ends_at
- sync_status

---

# 22. Roadmap Rules

시험 준비 로드맵은 PRD에서 정의한 축소 범위를 따른다.

포함:

- 시험일까지 남은 기간
- 총 학습 가능시간
- 시험과목
- 출제기준
- 기본학습 단계
- 문제풀이 단계
- 최종점검 단계
- 과목별 학습전략

제외:

- 일별 세부 공부계획
- 자동 취약과목 판단
- 교재 전체 세부 진도
- 합격 보장 표현

로드맵 기능이 MVP에서 제외되면 관련 테이블이나 복잡한 로직도 먼저 만들지 않는다.

---

# 23. FastAPI Rules

FastAPI Router는 가능한 한 얇게 유지한다.

기본 구조:

```text
Router
→ Service / LangGraph
→ Tool / DB / External API
```

Router 안에 전체 비즈니스 로직을 넣지 않는다.

예:

```python
@router.post("/agent/chat")
def chat(request: ChatRequest):
    result = graph.invoke({
        "user_id": request.user_id,
        "user_message": request.message,
    })

    return result
```

입출력 데이터는 가능한 경우 Pydantic 모델로 정의한다.

```python
class ChatRequest(BaseModel):
    user_id: int
    message: str
```

---

# 24. Database Rules

PRD에 정의된 DB 구조를 우선한다.

기본 테이블:

```text
users
user_profiles
certificates
schedules
exam_information
bookmarks
calendar_events
sources
api_sync_logs
```

시험 준비 로드맵 기능이 실제 구현될 경우에만 추가:

```text
roadmaps
roadmap_phases
```

기존 DB 구조를 확인하지 않고 새로운 테이블을 임의로 대량 생성하지 않는다.

---

# 25. MVP Priority

PRD의 MVP 범위를 우선 구현한다.

## 반드시 포함

- Google 로그인
- 프로필 입력
- 프로필 부족 여부 확인
- 응시 가능성 자격증 리스트
- 자격증 추천
- 자격증 상세정보
- 응시자격 확인
- 시험일정 조회
- 시험과목 조회
- 합격기준 조회
- 응시료 조회
- 공식 출처
- 시험회차 선택
- D-Day 계산
- Calendar 등록
- API 오류 Fallback
- 정보 부족 Fallback
- 결과 검증
- 자가성찰

## 구현 여부 판단 후 추가

- 시험 준비 로드맵
- 학습기간 Calendar 블록
- 북마크
- CBT 공식 링크

## MVP 이후

- 일별 상세 학습계획
- 진도율
- 카카오톡 알림
- 교재 목차 기반 계획
- 취약과목 자동 분석
- 합격률 통계
- NCS 기반 고도화 추천

MVP 이후 기능을 먼저 구현하지 않는다.

---

# 26. Coding Style

코드는 초급~중급 학습자가 읽을 수 있도록 작성한다.

다음 원칙을 따른다.

1. 역할이 분명한 함수명을 사용한다.
2. 변수명을 지나치게 축약하지 않는다.
3. 한 함수에 너무 많은 책임을 넣지 않는다.
4. 복잡한 한 줄 코드보다 명확한 여러 줄 코드를 우선한다.
5. 간단한 경우에만 리스트 컴프리헨션을 사용한다.
6. 불필요한 lambda 사용을 피한다.
7. Magic Number를 피한다.
8. 타입 힌트를 작성한다.
9. 중요한 함수에는 짧은 docstring을 작성한다.
10. 존재하지 않는 API, 함수, 패키지, 옵션을 임의로 만들지 않는다.

---

# 27. Avoid Overengineering

다음을 특별한 이유 없이 도입하지 않는다.

- 과도한 Base Class
- Factory Pattern
- Strategy Pattern
- 여러 단계의 Repository 추상화
- 지나치게 많은 Service 계층
- 복잡한 Dependency Injection
- 필요 없는 비동기 처리
- 기능 하나를 위한 과도한 클래스 구조

현재 프로젝트 규모에서 가장 단순하고 읽기 쉬운 구현을 우선한다.

---

# 28. Existing Code Rules

기존 코드가 있다면 먼저 구조를 파악한다.

확인 대상:

- imports
- 파일 구조
- 함수 이름
- 변수 이름
- Pydantic 모델
- DB 모델
- API Router
- LangGraph State
- Node
- Edge
- Tool
- 환경변수

기존 구조와 변수명을 최대한 유지한다.

오류와 관계없는 코드를 함부로 수정하지 않는다.

전체 프로젝트를 재작성하는 대신 최소 수정안을 우선한다.

---

# 29. Code Explanation Rules

코드를 작성한 뒤 사용자가 이해할 수 있도록 다음 순서로 설명한다.

1. 이 코드가 전체적으로 무엇을 하는지
2. 실행 순서
3. 핵심 함수의 역할
4. 입력값
5. 반환값
6. 오류 가능 지점

복잡한 Agent 코드라면 먼저 흐름을 보여준다.

```text
사용자 입력
→ FastAPI
→ LangGraph
→ Node
→ LLM 판단
→ Tool 선택
→ Tool 실행
→ ToolMessage
→ State 갱신
→ Validation
→ Router
→ Retry / Fallback
→ Final Answer
```

---

# 30. Error Handling Rules

에러가 발생하면 다음 순서로 처리한다.

```text
어디에서 발생했는가
→ 직접적인 원인은 무엇인가
→ 최소 수정 방법은 무엇인가
```

에러와 관계없는 구조를 전부 바꾸지 않는다.

다음을 구분한다.

- SyntaxError
- TypeError
- ValidationError
- HTTP / API Error
- DB Error
- Tool Error
- LangGraph State Error
- OAuth Error
- Calendar API Error

---

# 31. Pre-Code Checklist

코드를 작성하거나 수정하기 전에 내부적으로 확인한다.

- PRD 요구사항과 일치하는가?
- MVP 범위인가?
- import가 누락되지 않았는가?
- 변수명이 일치하는가?
- 함수 인자가 일치하는가?
- State key가 일치하는가?
- Tool 이름이 일치하는가?
- `tool_call_id`가 올바르게 연결되는가?
- `invoke()`와 `ainvoke()` 사용이 맞는가?
- sync / async가 섞이지 않았는가?
- DB Session 종료 처리가 필요한가?
- 외부 API Timeout 처리가 있는가?
- Retry 횟수가 제한되어 있는가?
- 날짜 순서 검증이 있는가?
- timezone을 고려했는가?
- Calendar 중복 검사가 있는가?
- 공식 출처가 저장 또는 반환되는가?
- 무한 반복 가능성이 없는가?

---

# 32. Forbidden Behaviors

다음을 하지 않는다.

- PRD와 다른 핵심 기능을 임의로 추가
- 존재하지 않는 라이브러리 API 생성
- 모든 판단을 LLM에게 맡기기
- 단순 조건문을 프롬프트로 해결하기
- 날짜 검증을 LLM에게 맡기기
- DB 중복 검사를 LLM에게 맡기기
- Calendar 중복 검사를 LLM에게 맡기기
- 공식 근거 없는 응시자격 생성
- 공식 출처 없이 확정적 정보 제공
- Tool 결과에 없는 정보 생성
- API 오류 시 무한 재시도
- 정보 없음과 Tool 오류를 동일하게 처리
- 사용자가 이해하기 어려운 과도한 추상화
- 기존 코드를 확인하지 않고 전체 구조 재작성

---

# 33. Recommended Implementation Order

전체 기능을 한 번에 구현하지 않는다.

다음 순서를 우선한다.

## Phase 1

```text
FastAPI
→ PostgreSQL 연결
→ users
→ user_profiles
```

## Phase 2

```text
Q-Net / 공공데이터 API 연동
→ 자격증 검색
→ 응시자격 조회
→ 시험일정 조회
→ 시험 상세정보 조회
```

## Phase 3

```text
@tool
→ Tool 목록
→ bind_tools()
→ tool_calls
→ Tool 실행
→ ToolMessage
```

## Phase 4

```text
LangGraph State
→ Node
→ Edge
→ Conditional Edge
→ Router
```

## Phase 5

```text
프로필 확인
→ 자격증 추천
→ 응시자격 비교
→ 부족 정보 추가 질문
```

## Phase 6

```text
validate_result
→ 오류 분류
→ Retry
→ Fallback
```

## Phase 7

```text
Google OAuth
→ Google Calendar
→ DB 중복 확인
→ Event ID 저장
```

## Phase 8

PRD와 일정상 필요한 경우에만:

```text
시험 준비 로드맵
```

---

# 34. Final Implementation Standard

항상 다음 질문을 기준으로 구현한다.

```text
1. PRD 요구사항에 맞는가?
2. 공식 정보에 근거하고 있는가?
3. LLM과 Tool의 역할이 분리되어 있는가?
4. Python으로 검증 가능한 것은 코드로 검증했는가?
5. 오류 발생 시 Retry / Fallback 경로가 있는가?
6. 사용자가 코드를 직접 읽고 수정할 수 있는가?
```

이 프로젝트의 핵심은 AI가 모든 것을 알아서 판단하는 것이 아니다.

다음 흐름을 안정적으로 구현하는 것이 핵심이다.

```text
사용자 정보
→ 공식 데이터 조회
→ Tool 실행
→ 조건 비교
→ 자격증 후보 탐색
→ 응시자격 판단
→ 시험정보 통합
→ 결과 검증
→ Retry / Fallback
→ Google Calendar 등록
→ 최종 응답
```
