# Q-Net API 설계 초안 v0.1

상태: 조회 API 일부 구현 완료. 아래의 실제 구현과 향후 검토안을 구분한다. 서버 배포·팀 합의는 진행 전이다.

**2026-10-05 검토 반영:** DB는 Render PostgreSQL. 프로필 저장과 단계별 일정 저장을 위한 DB 기반 코드를 작성했다. A06 응시조건 비교와 A08 Calendar는 보류, 로드맵은 제외했다. 북마크는 향후 포함하지만 현재 SQL/처리 코드는 주석으로 비활성화한다. 아래의 전체 API 목록은 검토용 제안으로 유지한다.

**현재 연결된 HTTP API:** /health, /health/database, /api/v1/certificates, /api/v1/certificates/{certificate_id}, /api/v1/certificates/{certificate_id}/schedules. 종목 검색의 현재 페이지 방식은 limit+offset이며 cursor는 향후 검토안이다. Render DB 미설정 상태에서는 검색·상세·일정 조회가 503을 반환한다. 공식 데이터 변환·동기화는 로컬 실행 명령으로 제공하며 공개 쓰기 API를 추가하지 않았다.

## 현재 구현과 다음 단계

| 메서드 | 실제 경로 | 상태와 범위 |
| --- | --- | --- |
| GET | `/health` | 서버 실행과 DB 설정 여부 |
| GET | `/health/database` | DB 접속·필수 테이블 존재 검사 |
| GET | `/api/v1/certificates` | 목록 613종목 검색. q/category/limit/offset 지원 |
| GET | `/api/v1/certificates/{certificate_id}` | 기술자격 510종목 상세정보. 미확보 자료는 null과 확인 상태 |
| GET | `/api/v1/certificates/{certificate_id}/schedules?year=2026` | 기술자격 475종목·1,922단계. UUID와 연도 필요 |

전문자격 100종목은 목록 검색만 연동했다. 다음 순서는 공식 상세정보·일정 제공 범위 조사와 실제 테스트 → 가능한 종목 확대 → Google 로그인 → 프로필 HTTP API → AI 기능이다. 구현 범위와 보류 사항은 [작업 현황](PROJECT_STATUS.md)을 따른다.

시험일정 응답은 기존 목록 형태를 유지한다. 기술사는 phase=`interview`를 지원하며 `registration_periods`에 실제 접수기간과 해당 출처·조회 시각을 포함한다. `registration_start/end`는 전체 범위다. 2026년 기사 3회 실기 접수는 9/21~9/23, 9/28 두 기간으로 표현한다. 상시검정 등으로 빈 목록을 반환해도 시험 미시행을 확정하는 것은 아니다. 응시자별 접수 가능 여부·접수 시간·시험장 배정은 별도 공식 확인이 필요하다.

기준: [PRD](../PRD.md), [공식 데이터 검증 결과](../research/feasibility_summary.json). 검증 기준일: 2026-10-05.

## A01. 범위와 기본 방식

업무 API는 FastAPI에서 `/api/v1`으로 제공하며 서버 상태 경로는 `/health` 아래에 둔다. 현재 구현 흐름은 직접 검색 → 상세정보 조회 → 단계별 일정 조회다. 이후 로그인·프로필·AI 연결을 진행한다. 응시조건 비교·Calendar는 보류, 북마크는 주석 상태, 로드맵은 범위 제외다.

일반 화면은 구현한 개별 API를 호출한다. A09의 대화 Agent는 향후 같은 서비스를 재사용하는 제안이다. 현재 공식 데이터 호출과 날짜 검증은 Python 코드가 수행하며 LLM은 아직 연결하지 않았다.

| 공통 항목 | 초안 |
| --- | --- |
| 사용자 식별 | 서버 로그인 세션에서 확인. 요청의 user_id를 신뢰하지 않음 |
| 인증 | 서버 세션 + HttpOnly 쿠키 제안. 실제 도메인 구성 후 쿠키/CORS 정책 확정 |
| 날짜 | 시험·접수는 `YYYY-MM-DD`, 조회 시각은 시간대 포함 ISO 8601 |
| 기준 시간대 | Asia/Seoul |
| 목록 | 현재 `limit` 기본 20, 최대 100 + `offset`; cursor는 향후 검토 |
| 출처 | 현재 source_url/실제 조회 시각을 직접 보관. 상세정보별 JSON과 각 접수기간에도 포함. sources 연결은 미구현 제안 |
| 비밀정보 | Google 토큰, 서비스 키, 내부 LLM 사고 과정은 응답/로그에 제외 |

## A02. 로그인 및 Calendar 권한

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| GET | `/auth/google/login` | Google 로그인 화면으로 이동 |
| GET | `/auth/google/callback` | 인증 결과 확인 후 세션 생성 |
| GET | `/me` | 현재 로그인 사용자 |
| POST | `/auth/logout` | 세션 종료 |
| GET | `/integrations/google-calendar/authorize` | 사용자가 요청한 Calendar 권한 연결 시작 |
| GET | `/integrations/google-calendar/callback` | Calendar 권한 결과 저장 |
| GET | `/integrations/google-calendar/status` | 연결 여부 및 재동의 필요 여부 |

로그인 동의와 Calendar 동의를 분리한다. 권한 연결만으로 일정은 생성하지 않는다. OAuth state 검증, 허용된 리다이렉트 주소, 세션 만료 및 변경 요청의 CSRF 방어를 적용한다. Google 실제 연동은 아직 테스트하지 않았으며 세부 scope는 연동 구현 전에 공식 문서로 확정한다.

## A03. 사용자 프로필

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| GET | `/me/profile` | 저장된 프로필 조회 |
| PATCH | `/me/profile` | 전달한 필드만 저장; 부분 입력 허용 |
| GET | `/me/profile/completeness?purpose=recommendation` | 다음 단계에 부족한 정보 확인 |

프로필 HTTP API는 미구현이며 DB·입력 검증·저장 함수는 준비했다. 필드는 DB 문서 D03과 동일하다. 필드 생략은 유지, 일반 필드 null은 삭제, 경력·보유 자격 배열 null은 []로 초기화한다. 학력이 고졸인 경우처럼 적용되지 않는 전공과 아직 모르는 전공을 구분한다. 보유 자격·경력 날짜는 필요한 경우 추가 입력받는다. 로드맵 관련 학습시간 필드는 제외한다.

충분성 검사 예시:

```json
{
  "purpose": "recommendation",
  "ready": false,
  "missing_fields": ["desired_job"],
  "questions": [{"field": "desired_job", "message": "희망하는 직무를 알려주세요."}]
}
```

기본 추천에 필요한 정보와 특정 자격의 응시조건 판단에 필요한 정보는 별도로 검사한다. 경력이 없다는 명시적 답변은 정보 누락으로 취급하지 않는다.

## A04. 자격증 검색 및 상세

현재 검색·단계별 일정 API에 더해 `GET /api/v1/certificates/{certificate_id}`를 구현했다. 기술자격 510종목의 과목·합격기준·응시료를 `exam_information.subjects`, `pass_criteria`, `fees`로 반환하며 각각 written/practical/interview/phases/status/source_url/retrieved_at을 포함한다. 과목·기준은 단계 구분 없는 common 문구도 제공한다. 응시료는 currency=KRW다. 세 정보 확보 464개는 data_status=complete, 일부 미확인 46개는 partial이다. 미수집 종목은 200과 data_status=unavailable, 값 null, 공식 페이지 링크로 응답한다. 없는 UUID는 404다. 아래 예시는 이전 제안이며 실제 응답과 실행 방법은 [시험 상세정보 설명](EXAM_INFORMATION.md), 종목별 현황은 [확대 결과](DETAIL_EXPANSION_RESULTS.md)를 따른다.

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| GET | `/certificates?q=정보처리&category=T&limit=20` | 공식 목록 기반 검색 |
| GET | `/certificates/{certificate_id}` | 과목, 합격 기준, 수수료, 관련 학과/직무, 공식 링크 |
| GET | `/certificates/{certificate_id}/schedules?year=2026` | 회차와 시험 단계 목록 |
| GET | `/schedules/{schedule_id}` | 특정 시험 단계와 접수 상태, D-Day |

certificate_id는 내부 UUID, qnet_code는 공식 종목 코드 문자열이다. category는 공식 분류 T/S 등을 보존한다. 모든 목록 항목이 현재 시행 중이라는 보장은 하지 않는다.

상세 응답의 주요 구조:

```json
{
  "id": "<certificate UUID>",
  "qnet_code": "1320",
  "name": "정보처리기사",
  "data_status": "partial",
  "subjects": {"value": [], "source_ids": [], "status": "unavailable"},
  "pass_criteria": {"value": null, "source_ids": [], "status": "unavailable"},
  "fees": {"value": {"written": 19400, "practical": 22600, "currency": "KRW"}, "source_ids": ["<source UUID>"], "status": "available"},
  "exam_sites": {"value": null, "source_ids": [], "status": "unavailable"},
  "sources": [{"id": "<source UUID>", "source_type": "api", "source_url": "<공식 출처 URL>", "retrieved_at": "<실제 조회 시각>"}]
}
```

UUID와 시각은 형식 설명용이다. 수수료만 검증 당시 실측값을 예시로 사용했다. 배열이 비었다는 이유로 '과목 없음'으로 해석하지 않도록 status를 함께 제공한다. 개인별 시험장은 확인 전까지 미확정이며 일반 시험장 목록과 구분한다.

## A05. 후보 추천

`POST /me/certificate-recommendations`

저장된 프로필로 계산한다. 요청은 `{"limit": 10}`이며 기본 5, 최대 20을 제안한다. 프로필 부족 시 HTTP 200으로 `status: needs_more_info`, missing_fields, questions를 반환한다.

충분하면 `status: ready`, candidates 배열을 반환한다. 후보별 필드:

| 필드 | 의미 |
| --- | --- |
| certificate_id, name | 자격증 |
| eligibility_status | A06의 판단 상태 |
| reasons | 추천 근거; 직무 연관성과 응시조건 근거를 구분 |
| missing_fields | 추가 확인할 프로필 항목 |
| next_schedule | 검증된 다음 일정 또는 null |
| registration_status | open / upcoming / closed / unknown |
| source_ids | 공식 근거 |

공식 응시조건 → 팀이 정의할 career_tags → 프로필 적합도 → 실제 접수 가능 일정 → 정보 충분성 순으로 후보를 정렬한다. 숫자 점수를 합격 확률처럼 노출하지 않는다. career_tags 미합의 상태에서는 공식 직무 분류와 사용자 직접 검색부터 제공한다.

## A06. 응시자격 판단

현재 보류 상태다. 아래는 이전 검토안이며 응시조건 JSONB 저장·reviewed 경로 비교를 구현하지 않는다.

`POST /certificates/{certificate_id}/eligibility`

저장 프로필과 공식 조건을 비교한다. 요청 본문은 생략 가능하다. 결과는 법적 자격 확정이나 서류 심사 결과가 아닌 사전 안내다.

| status | 화면 문구 | 사용 조건 |
| --- | --- | --- |
| eligible | 응시 가능성이 높음 | 확인한 조건 경로와 입력이 일치 |
| needs_more_info | 추가 정보 필요 | 판단에 필요한 사용자 정보 부족 |
| possibly_ineligible | 조건 미충족 가능성 | 확인한 조건 경로에 현재 입력이 부합하지 않음 |
| unknown | 공식 확인 필요 | 근거 부족, 규칙 해석 불가, 자료 충돌 |

응답: status, matched_paths, unmet_conditions, missing_fields, questions, source_ids, evaluated_at, profile_updated_at, rule_version, official_confirmation_url.

응시조건은 여러 경로 중 하나를 충족하는 OR 구조로 다룬다. 단순 career_years 비교로 단정하지 않는다. 관련 전공·직무 인정, 졸업 여부, 자격 취득 이후 경력, 기준일까지의 경력을 확인한다. 공식 목록의 seriescd와 응시조건 grdCd는 별도 코드이므로 검증한 매핑만 적용한다.

## A07. 회차 선택과 날짜

현재 일정 API는 단계별 행의 목록을 반환한다. 같은 회차는 `round_key`로 묶으며 각 행의 `id`가 일정 UUID다. 기술사는 written/interview, 다른 기술자격은 written/practical을 지원하고 실기 단독도 보관한다. 전문자격의 1차/2차 매핑과 회차 선택 상태 저장은 후속 작업이다.

현재 응답 필드: id, certificate_id, year, round_key, round_label, phase, registration_start/end, registration_periods, exam_start/end, result_date, result_display_end, vacancy_registration_start/end, exam_site, source_url, last_synced_at, updated_at. registration_periods는 실제 접수기간과 그 출처·조회 시각을 포함한다. registration_status, d_day, source_ids, 일정 data_status는 미구현 제안이다.

`d_day`는 `{"days": 19, "basis": "exam_start", "date": "2026-10-24", "label": "시험기간 시작까지"}` 형태다. 개인 시험일을 모르면 기간 시작 기준임을 표시한다. 지난 날짜는 미래 일정으로 노출하지 않는다. 접수 종료와 시험 종료를 각각 판단한다. 조회일에 따라 계산하므로 D-Day를 DB에 고정 저장하지 않는다.

시험기간과 결과 조회 종료일은 시험일/발표일과 구별한다. 상시시험이나 조회 결과가 없는 종목은 일정을 추정하지 않고 공식 확인 링크를 제공한다.

## A08. Google Calendar 등록

현재 보류 상태다. 아래의 primary 제한·중복 방지·외부 생성 흐름은 이전 검토안이며 이번 구현에 포함하지 않는다.

`POST /me/calendar-events`

```json
{
  "schedule_ids": ["<필기 schedule UUID>", "<실기 schedule UUID>"],
  "event_types": ["registration", "exam", "result"],
  "calendar_id": "primary"
}
```

사용자가 화면에서 일정과 기간을 확인하고 등록 버튼을 누른 요청으로만 실행한다. 대화의 정보 조회만으로 실행하지 않는다. MVP는 primary 캘린더만 지원하는 안이다. 과거 일정은 제외하고 excluded_items로 이유를 반환한다.

등록 전 소유권·Calendar 권한·공식 출처·날짜 순서·기존 이벤트를 검증한다. 기간 일정은 종일 이벤트로 만들며 내부 종료일은 포함 날짜, Google 전달 종료일은 제공자 규칙에 맞춰 변환한다. 실제 변환은 연동 테스트에서 확인한다.

DB 고유키로 중복을 막고, 외부 생성 후 DB 저장 실패에도 복구할 수 있는 제공자 이벤트 식별 방식은 Google 연동 시 검증한다. 결과가 불명확하면 즉시 재생성하지 않는다.

응답 HTTP 200: items 각각 `created / already_exists / excluded / failed / unknown`, calendar_event_id, google_event_id, error_code를 제공한다. 일부 성공을 전체 실패로 숨기지 않는다. `GET /me/calendar-events`로 등록 결과를 확인한다. 일정 수정·삭제 및 자동 변경 동기화는 MVP 초안 범위에 넣지 않는다.

## A09. 대화 Agent

미구현 제안이다. 로그인·프로필 연결 이후 RAG·tool calling·LangChain·LangGraph 범위를 검토한다.

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| POST | `/agent/sessions` | 대화 세션 생성 |
| POST | `/agent/sessions/{session_id}/messages` | message와 선택 항목 전달 |
| GET | `/agent/sessions/{session_id}` | 현재 선택 및 진행 상태 조회 |

메시지 응답: session_id, status(`completed / needs_more_info / needs_confirmation / unavailable`), answer, structured_result, questions, sources, validation_errors. 세션은 로그인 사용자만 접근한다.

State에는 선택한 자격/회차, 부족한 정보, 도구 결과 요약, 검증 오류, retry_count를 저장한다. 상세 비공개 추론은 저장하거나 반환하지 않는다. 일시 오류는 코드에서 최대 1회 재시도하고 이후 공식 페이지/확인 필요 안내로 전환한다. 빈 조회 결과를 통신 오류로 취급하지 않는다. Calendar 등록은 A08의 명시적 동의 경로를 사용한다.

## A10. 선택 기능

로드맵은 현재 작업 범위에서 제외한다. 관련 API·테이블·학습시간 필드를 만들지 않는다. 향후 사용자가 다시 결정한다.

북마크는 향후 포함한다. 현재 테이블 SQL과 생성·조회·삭제 함수는 전체 주석 상태다. 활성화 및 HTTP API 연결은 후속 작업이다.

## A11. 오류와 공식 데이터 운영

오류 구조: `{"error": {"code": "CALENDAR_AUTH_REQUIRED", "message": "Calendar 연결이 필요합니다.", "retryable": false}, "request_id": "<추적 ID>"}`.

| HTTP | 용도 |
| --- | --- |
| 401 / 403 | 로그인 필요 / 권한 부족 |
| 404 | 없는 자격증·일정·사용자 소유 세션 |
| 409 | 변경된 일정 등으로 이전 요청 내용과 충돌; 재확인 필요 |
| 422 | 잘못된 필드 형식·허용하지 않는 값 |
| 429 | 요청 한도 초과 |
| 503 | 대체 출처/캐시까지 없어 요청 수행 자체가 불가 |

프로필 부족과 응시조건 불확실성은 정상적인 업무 결과로 HTTP 200을 쓴다. 일부 공식 정보가 없으면 data_status=partial로 사용 가능한 정보와 미확인 항목을 함께 반환한다.

공식 API → 검증된 DB 캐시 → 공식 문서 RAG → 공식 페이지 → 확인 필요 순으로 처리한다. 캐시 조회도 원본 출처와 원본 조회 시각을 유지한다. 잘못된 최신 응답으로 검증된 캐시를 덮어쓰지 않는다. 일반 사용자가 전체 동기화를 실행하는 공개 API는 만들지 않는다.

현재 실측: 목록 613종목, 기술자격 상세정보 510종목, 기술자격 일정 475종목·1,922단계. 상세정보 46종목은 일부 미확인, 3종목은 미확보다. 일정 미연동 38종목의 사유는 [확대 결과](SCHEDULE_EXPANSION_RESULTS.md)에 기록했다. 실제 API는 검증된 DB를 조회하고 갱신은 수동 실행 명령으로 처리한다. RAG·Google 연동과 자동 갱신은 미구현이다. 초기 통합 일정 API의 인증 실패·종목 API 시간초과 등은 조사 기록에 남겼다.

## A12. 검토할 결정

1. 인증: 서버 세션 쿠키 방식으로 시작할지. 프론트/백 도메인 구성 후 정책 확정.
2. 기본 프로필: 학력·졸업 상태·전공·경력 여부·희망 직무 중 화면에서 먼저 받을 항목.
3. 일정: 회차 아래 단계별 UUID·기간 저장과 복수 접수기간 구조는 확정·구현 완료.
4. 응시자격: 보류. 재개 시 상태·안내 문구를 검토.
5. Calendar: 보류. 재개 시 primary·중복 방지·선택 등록 정책을 검토.
6. Agent: 기본 화면과 대화 화면 모두 MVP에 포함할지.
7. 북마크는 향후 포함하되 현재 주석 상태. 로드맵은 범위 제외·향후 결정.

현재 작업 순서: 전문자격 공식 상세정보·일정 조사 및 확대 → A02 로그인 → A03 프로필 API → A09 AI 기능. 프론트 연동·배포 설정은 팀과 맞춰 진행한다.
