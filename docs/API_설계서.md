# 자격잇다 API 설계서

작성일: 2026-10-12 · 경로 접두사 `/api`, `/v1` 없음 · FastAPI / Render PostgreSQL

> 최신 회의 결정에 따라 **서비스 Google 로그인과 Bearer 인증을 사용하지 않는다.** 프로필은 프론트가 보관하고 추천 요청에 포함한다. Google Calendar는 일정 등록이 필요한 경우에만 별도로 연결한다. 이 결정은 PRD의 초기 로그인 흐름을 대체한다.

## 핵심 흐름

```text
자격증 탐색은 공개
프로필 입력 → 프론트에 저장 → POST /recommendations에 입력 포함 → 최대 10개 추천
Calendar 등록 버튼 → Google Calendar 전용 동의 → HttpOnly 쿠키 → 선택 일정 등록
```

서버는 추천 프로필을 저장하지 않는다. `/me/profile` 조회·수정 API와 `/auth/*` 로그인·토큰 API는 제공하지 않는다. 프론트는 프로필을 브라우저에 보관하고 추천 요청마다 본문에 실어 보낸다.

## 엔드포인트

| 기능 | 메서드·경로 | 인증 | 설명 |
|---|---|---|---|
| 관심 분야 | `GET /interest-categories` | 공개 | 서비스 선택지 24개 반환 |
| 추천 | `POST /recommendations` | 공개 | 요청 프로필을 기준으로 LLM 관련성 순 최대 10개 반환 |
| 자격증 검색 | `GET /certificates` | 공개 | 공식 종목명·코드 검색 |
| 자격증 상세 | `GET /certificates/{certificate_id}` | 공개 | 시험과목·합격기준·응시료와 출처 |
| 시험 일정 | `GET /certificates/{certificate_id}/schedules?year=2026` | 공개 | 회차·단계별 일정 |
| 종목별 추천 대상·연관 직무 | `GET /certificates/{certificate_id}/career-info` | 공개 | 공통 안내·검토된 직무·근거 |
| Calendar 연결 시작 | `GET /calendar/google/authorize` | 공개 | 권한 동의 주소를 반환하고 OAuth state 쿠키 설정 |
| Calendar 연결 완료 | `POST /calendar/google/callback` | OAuth state 쿠키 | Google 토큰을 저장하고 Calendar 전용 쿠키 설정 |
| Calendar 일정 등록 | `POST /calendar/register` | Calendar 전용 쿠키 | 사용자가 고른 일정만 기본 캘린더에 등록 |

현재 등록하지 않는 경로: `/auth/google/authorize`, `/auth/google`, `/auth/refresh`, `/auth/logout`, `/me/profile`.

## 추천 요청

`POST /recommendations`는 body에 사용자 ID나 별도 `profile` 래퍼를 넣지 않는다. 프로필 입력 필드를 그대로 전달한다.

```json
{
  "interest_category_codes": ["20"],
  "education_level": "university",
  "education_status": "graduated",
  "major": "컴퓨터공학",
  "has_career": false,
  "career_years": null
}
```

| 필드 | 허용값·규칙 |
|---|---|
| `interest_category_codes` | `01`~`24` 중 정확히 한 개의 문자열 배열 |
| `education_level` | `high_school_or_below`, `college`, `university`, `graduate_school`, `other` |
| `education_status` | `graduated`, `enrolled`, `expected`, `other` |
| `major` | 문자열 또는 `null`, 선택값 |
| `has_career` | 필수 Boolean |
| `career_years` | 경력 있으면 0~80 숫자, 없으면 `null` |

화면에는 `전문대`, `졸업` 같은 한글을 보여주고, 요청에는 위 enum 코드를 보낸다. 알 수 없는 필드는 거절한다. 프로필 누락·형식 오류는 추천 실행 전에 `422`를 반환한다.

성공 응답의 주요 필드는 기존 추천 계약을 유지한다.

```json
{
  "status": "completed",
  "ordering": "llm_relevance",
  "selection_scope": "searched_candidates_only",
  "total_count": 1,
  "initial_display_count": 1,
  "items": []
}
```

후보가 1~2개면 있는 만큼 반환하고, 후보가 없으면 `status: "no_results"`, `total_count: 0`, `items: []`을 반환한다. 최대 10개이며 첫 화면 표시 수는 최대 3개다. 더보기는 동일 응답의 `items`를 프론트에서 펼친다.

## 자격증 조회

- `GET /certificates?q=&category=&limit=20&offset=0`: 공개 목록. `category`는 공식 분류 `T`(국가기술자격), `S`(국가전문자격)다.
- `GET /certificates/{certificate_id}`: 기본정보·시험정보·정보별 확인 상태·공식 출처를 반환한다. 확인되지 않은 값은 `null`과 상태로 구분한다.
- `GET /certificates/{certificate_id}/schedules?year=2026`: 단계별 일정 행을 반환한다. `registration_periods`가 있으면 실제 접수 구간을 우선한다.
- `GET /certificates/{certificate_id}/career-info`: 자격증에 공통인 추천 대상과 근거가 확인된 연관 직무를 반환한다. 취업 보장 표현은 하지 않는다.

목록·상세·일정은 Render PostgreSQL에 저장된 공식 자료를 사용한다. DB 연결 또는 필수 테이블 조회에 실패하면 `503`이다. 빈 일정 배열은 저장된 일정이 없다는 의미이며 미시행을 확정하지 않는다.

## Google Calendar 전용 연결

### 1. 연결 시작

프론트는 쿠키 처리를 위해 `credentials: "include"`로 다음 API를 호출한다.

```http
GET /calendar/google/authorize
```

200 응답:

```json
{"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?..."}
```

응답 주소로 브라우저를 이동한다. Google에는 Calendar 일정 관리 scope만 요청하며 앱 사용자 로그인, 이메일, 서비스 Bearer 토큰은 발급하지 않는다. 서버는 5분짜리 OAuth state와 HttpOnly 확인 쿠키를 사용한다.

### 2. 동의 완료

Google은 등록된 `GOOGLE_REDIRECT_URI`로 돌아온다. 프론트 콜백은 `code`, `state`를 읽어 다음 요청을 보낸다.

```http
POST /calendar/google/callback
Content-Type: application/json
```

```json
{"code": "google-authorization-code", "state": "one-time-state"}
```

요청에도 `credentials: "include"`가 필요하다. 성공 응답은 다음과 같고, 응답 헤더에는 30일짜리 `qnet_calendar_session` HttpOnly 쿠키가 설정된다.

```json
{"calendar_connected": true, "expires_in": 2592000}
```

Google refresh token은 암호화해 DB에 저장하고, 쿠키 원문 대신 해시를 저장한다. 프론트는 Google 토큰이나 Calendar 세션 토큰을 읽거나 저장하지 않는다. 30일이 지나면 Calendar를 다시 연결해야 한다.

### 3. 일정 등록

사용자가 시험회차와 등록 항목을 선택한 후 호출한다. Bearer 헤더는 보내지 않고 Calendar 쿠키를 포함한다.

```http
POST /calendar/register
Idempotency-Key: <새 UUID>
Content-Type: application/json
```

```json
{
  "certificate_id": "33333333-3333-4333-8333-333333333333",
  "schedule_ids": ["44444444-4444-4444-8444-444444444444"],
  "schedule_versions": {
    "44444444-4444-4444-8444-444444444444": "2026-10-08T06:00:00Z"
  },
  "event_types": ["registration", "written_exam", "practical_exam", "result"]
}
```

`event_types`는 사용자가 선택한 종류만 보낸다. 종류는 `registration`(원서접수 기간), `written_exam`(필기시험), `practical_exam`(실기시험), `result`(합격발표일)이다. 서버는 선택 회차의 공식 날짜와 출처를 다시 확인하고, 기본 Google Calendar에 새 이벤트를 추가한다. 일정이 갱신됐으면 `409 SCHEDULE_CHANGED`, Calendar 연결이 없거나 만료됐으면 `401`, Google 권한이 거절됐으면 `403`, DB 준비가 안 됐으면 `503`이다.

일정 등록 SQL은 자동 적용하지 않는다. 개발 DB를 확인한 뒤 `backend/db/calendar_registration.sql`을 적용해야 한다. 이 스키마는 `users` 테이블과 연결하지 않는다.

## 프론트 연결 변경점

1. 로그인 화면·Bearer 토큰·`/auth/*` 호출을 제거한다.
2. 프로필 저장은 브라우저 로컬 저장소로 처리하고, 추천마다 위 프로필 body를 보낸다.
3. 마이페이지는 로그인 계정별 서버 프로필이 아니라 현재 브라우저에 보관한 프로필을 수정한다.
4. Calendar 연결이 필요할 때만 위 OAuth 흐름을 사용한다. callback과 등록 요청에 `credentials: "include"`를 설정한다.
5. 백엔드의 `AUTH_ALLOWED_ORIGINS`에는 프론트 origin을 등록하고, 운영 HTTPS에서는 `AUTH_COOKIE_SECURE=true`를 설정한다.

프론트 코드는 이 변경에서 수정하지 않았다. 기존 로그인·`/me/profile` 계약에 맞춘 프론트 호출은 새 계약으로 전환되어야 동작한다.

