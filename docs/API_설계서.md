# 자격잇다 API 설계서

작성일: 2026-10-12 · 경로 접두사 `/api`, `/v1` 없음 · FastAPI / Render PostgreSQL

> 회의에서 확정한 요구사항과 현재 `backend/main.py`, `backend/schemas.py`, DB 구조를 기준으로 작성한 구현 계약이다. **문서 작성은 기능 구현 완료를 뜻하지 않는다.** Figma 최종본(88:3)은 연결 도구 호출 한도와 브라우저 실행 오류로 직접 검증하지 못했다. 마이페이지는 사용자가 별도로 확정한 **프로필 조회·수정만** 반영했다. 화면 필드와 최종 대조가 필요한 항목은 12절에 표시했다.

## 1. 적용 범위

### 프로필 입력 최신 결정 — 2026-10-12

프로필 입력·조회·부분 수정 API와 추천에서 저장 프로필을 읽는 기능은 구현하고 `main.py`에 등록했다. 보호 라우터에는 Google 로그인 공통 `get_current_user()`를 연결했다. 공용 DB SQL 적용은 남아 있다. [프로필 API 연결 안내](프로필_API_연결안내.md)에 입력·수정 버전·null 처리·현재 상태를 정리했다.

추천은 선택한 관심 분야·저장 프로필·공식 직무 근거를 바탕으로 LLM이 적합한 순서로 최대 10개를 반환한다. 첫 3개를 우선 보여주고 더보기는 같은 응답을 펼친다. 종목별 공통 추천 대상·연관 직무 API는 `GET /certificates/{certificate_id}/career-info`다. 두 추천 경로 모두 인증 및 `main.py` 등록까지 연결했으며, DB 준비와 실제 호출 확인은 남아 있다. [추천 API 연결 안내](추천_API_연결안내.md)에 현재 상태를 정리했다.

이 절의 프로필 결정은 아래 이전 필드 제안보다 우선한다. 관심 분야 1개·최종 학력·졸업 상태·관련 경력 유무를 필수로 받는다. 전공은 선택이며 희망 직무·경력 분야·직무명·근무 날짜는 현재 입력에서 제외한다. 경력 있을 때만 관련 경력 년차를 숫자로 받고, 경력 없으면 null이다.

| 필드 | 현재 입력 계약 |
|---|---|
| interest_category_codes | 01~24 중 정확히 한 개의 문자열 배열 |
| education_level | high_school_or_below(고졸 이하), college(전문대), university(대학교), graduate_school(대학원), other(기타) |
| education_status | graduated(졸업), enrolled(재학), expected(졸업 예정), other(기타) |
| major | 선택 문자열, 빈 입력은 null |
| has_career | 필수 Boolean |
| career_years | 경력 있으면 0~80 숫자, 없으면 null |

학력과 졸업 상태는 각각 선택형이다. 입력 검증·저장·조회 API와 추천 프로필 조회 연결은 구현되어 있다. DB 마이그레이션과 관심 분야 데이터 적용은 남아 있다. 경력 년차를 근무 날짜로 추정하거나 선택 관심 분야를 실제 경력 분야로 저장하지 않는다.

| 구분 | 확정 내용 |
|---|---|
| 시작 | Google 로그인 필수, 로그인 과정에서 Calendar 권한도 요청 |
| 프로필 | NCS 대분류 명칭을 가져온 서비스 선택지 24개 중 정확히 1개(공식 NCS 분류 판정 아님), 최종 학력·졸업 상태·경력 유무 필수, 전공 선택 |
| 추천 | DB 후보 중 LLM 적합도 순으로 최대 10개 반환, 대표 3개 우선 표시 |
| 더보기 | 동일 결과에서 총 최대 10개까지 표시. 새 LLM 호출 없음 |
| 후보 부족 | 1~2개도 그대로 표시, 0개이면 없다는 안내 |
| 응답 방식 | 추천 결과가 나올 때까지 로딩 후 한 번에 응답. 추가 질문 분기 없음 |
| 제외 | 재추천 버튼, 이전 추천 내역, 챗봇, 회원 탈퇴, 등록 일정 조회 화면/API |
| 마이페이지 | 저장된 프로필 조회·수정. 수정만으로 추천을 자동 실행하지 않음 |
| Calendar | 원서접수 기간·필기시험·실기시험·합격발표일, 기본 캘린더에 새 이벤트 추가 |
| 일정 저장 | 회차 선택만으로 저장하지 않고 Calendar 등록 요청 때 저장 |
| 수정·삭제 | 서비스에서는 제공하지 않음. 사용자가 Google Calendar에서 직접 처리 |
| 인증 | Bearer 액세스 토큰 30분. 리프레시 쿠키는 30일 슬라이딩 갱신, DB 세션은 로그아웃 또는 보안상 폐기 때 종료 |
| 이번 문서 제외 | 배포, 로드맵, 북마크, 자동 응시자격 확정 판정 |

아래 JSON 필드·상태명·오류 코드·OAuth 전달 방식은 협업을 위한 **설계 제안**이다. 회의에서 정한 제품 범위와 구분하며, 담당자가 구현 전에 이 계약으로 통일한다.

## 2. 공통 규칙

- JSON UTF-8, 필드 이름 `snake_case`. 자격증·일정·사용자 내부 ID는 UUID, Q-Net 코드는 문자열이다.
- 인증이 필요한 요청은 `Authorization: Bearer <access_token>`을 사용한다. 요청 body의 `user_id`를 신뢰하지 않고 토큰에서 현재 사용자를 결정한다.
- 시각은 ISO 8601 UTC(`Z`), 시험 날짜는 `YYYY-MM-DD`, 화면 및 Calendar 기준 시간대는 `Asia/Seoul`이다.
- 미확인 값은 `null`이다. 응시료 `null`은 무료가 아니며, 면접 정보 `null`은 면접 없음이 아니다.
- 기존 조회 API의 성공 응답 구조를 유지한다. 목록은 배열이며 전역 `data` 래퍼를 추가하지 않는다.
- 신규 입력은 알 수 없는 필드를 거절한다. 실패 응답에는 토큰·DB 연결 문자열·내부 스택을 넣지 않는다.
- 인증·요청 크기·권한·소유권·날짜·중복 검사는 Python에서 처리한다.

### 공통 오류 형식 — 구현 시 기존 오류 형식도 통일

```json
{
  "error": {
    "code": "PROFILE_INCOMPLETE",
    "message": "필수 프로필을 입력해주세요.",
    "fields": ["education_level"],
    "retryable": false
  },
  "request_id": "req-example"
}
```

| HTTP | 용도 / 대표 코드 |
|---|---|
| 400 | 잘못된 OAuth state, 유효하지 않은 작업 요청 |
| 401 | `ACCESS_TOKEN_EXPIRED`, `SESSION_REVOKED`, `REFRESH_TOKEN_INVALID` |
| 403 | `CALENDAR_PERMISSION_REQUIRED`, 다른 사용자 자원 접근 |
| 404 | 자격증·서버 작업 자원 없음 |
| 409 | `PROFILE_CHANGED`, `SCHEDULE_CHANGED`, `IDEMPOTENCY_CONFLICT`, `REQUEST_IN_PROGRESS` |
| 422 | 필드 검증 실패, `PROFILE_INCOMPLETE`, 선택 일정 불일치 |
| 429 | 호출 제한. 필요 시 `Retry-After` 제공 |
| 502 | 외부 서비스 응답 오류 / 검증 실패 |
| 503 | DB 또는 필수 서비스 이용 불가 |
| 504 | 추천·외부 호출 제한 시간 초과 |

현재 공통 `error/request_id` 래퍼는 인증 오류에만 적용된다. 프로필·추천 오류와 FastAPI 기본 422 응답은 아직 이 형식으로 통일하지 않았다. 추천 후보 0개, 일부 시험정보 누락은 서버 오류가 아닌 정상 응답이다.

## 3. 엔드포인트 목록

| 기능 | 메서드·경로 | 인증 | 현재 상태 |
|---|---|---|---|
| Google 인증 시작 | `GET /auth/google/authorize` | 불필요 | dev에 병합·등록됨 |
| Google 코드 교환·로그인 | `POST /auth/google` | OAuth 거래 검증 | dev에 병합·등록됨. Calendar 저장 함수가 없어 현재 실제 로그인 완료는 503 |
| 로그인 사용자 | `GET /auth/me` | Bearer | 미구현 |
| 토큰 갱신 | `POST /auth/refresh` | 리프레시 쿠키 | dev에 구현·등록됨. 액세스 토큰 30분, 리프레시 쿠키 30일 슬라이딩 |
| 로그아웃 | `POST /auth/logout` | 로그인 세션 | dev에 구현·등록됨 |
| 서비스 관심 분야 목록 | `GET /interest-categories` | Bearer | 구현·등록됨. 관심 분야 테이블 적용 대기 |
| 프로필 조회 | `GET /me/profile` | Bearer | 구현·등록됨. 프로필 SQL 적용 대기 |
| 최초 프로필 저장·부분 수정 | `PATCH /me/profile` | Bearer | 구현·등록됨. 프로필 SQL 적용 대기 |
| 추천 결과 생성 | `POST /recommendations` | Bearer | 구현·등록됨. 프로필·추천 자료 DB 적용 대기 |
| 자격증 검색 | `GET /certificates` | 공개 | 조회 구현됨. 로그인 전에도 종목 탐색 가능 |
| 자격증 상세 | `GET /certificates/{certificate_id}` | 공개 | 조회 구현됨 |
| 종목별 공통 추천 대상·연관 직무 | `GET /certificates/{certificate_id}/career-info` | Bearer | 구현·등록됨. 추천 자료 DB 적용 대기 |
| 시험 일정 | `GET /certificates/{certificate_id}/schedules` | 공개 | 조회 구현됨 |
| Calendar 등록 | `POST /calendar/register` | Bearer + Google 권한 | 구현·Swagger 등록됨. Calendar SQL 적용과 Google 실계정 검증 대기 |

`/health`, `/health/database`, `/docs`는 개발·운영용 기존 경로로 유지한다. 사용자 화면 기능 목록에는 포함하지 않는다.

Google 인증은 dev에 병합되어 로그인 시작·완료, 갱신, 로그아웃과 공통 Bearer 검증이 등록되어 있다. 로그인 완료는 Calendar 갱신 토큰을 암호화 저장하는 함수에 연결되어 있다. `/auth/me`와 실제 Google·DB 연동 확인은 미완료다. DB 세션에는 고정 만료가 없고, 리프레시 쿠키는 30일 만료로 설정하며 갱신 때마다 새 만료를 적용한다. 새 프로필·추천 API도 `get_current_user()`에 연결했지만 관련 SQL은 아직 공용 DB에 적용하지 않았다. Calendar 등록 코드도 `get_current_user()`와 저장 토큰을 재사용하지만, `google_calendar_credentials.sql`과 `calendar_registration.sql`은 대상 DB에 별도 적용해야 한다.

별도 `/agent/run`, 작업 폴링, 추가 답변, 추천 이력, Calendar 내역·수정·삭제 API는 만들지 않는다. RAG와 LangGraph는 추천·정보 보완의 백엔드 내부 처리이며, 화면 요구가 없는 독립 엔드포인트를 추가하지 않는다.

## 4. Google 로그인·인증 계약

### 4.1 로그인 시작과 완료

`GET /auth/google/authorize` → 200:

```json
{"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?..."}
```

서버가 짧은 수명의 일회용 state와 브라우저 거래를 연결한다. 로그인 식별 범위와 Calendar 쓰기 범위를 함께 요청한다. 리다이렉트 주소는 서버에 고정 등록하며 임의 URL을 요청받지 않는다.

Google이 프론트의 정해진 콜백 페이지로 `code`, `state`를 보내면 다음 요청을 한다.

`POST /auth/google`:

```json
{"code": "google-authorization-code", "state": "one-time-state"}
```

200:

```json
{
  "access_token": "service-access-token",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {"id": "11111111-1111-4111-8111-111111111111", "email": "user@example.com"},
  "profile_completed": false,
  "calendar_connected": true
}
```

- state·브라우저 거래·일회용 code를 검증하고 서버에서 Google 토큰을 교환한다. 사용자 식별은 검증된 Google `sub`를 사용한다.
- ID 토큰만 전달받는 로그인으로는 Calendar 접근 권한을 확보할 수 없다.
- 사용자 회원 키는 기존 DB의 `(provider, provider_subject_id)`를 유지한다. 이메일을 사용자 식별 키로 대체하지 않는다.
- Calendar 동의를 거절해도 Google 로그인 자체가 성공하면 서비스 로그인은 허용하고 `calendar_connected=false`로 반환하는 것을 제안한다. 등록은 403으로 차단하고 동일 인증 흐름으로 재동의를 안내한다.
- **서비스 토큰과 Google 토큰은 별개**다. Google 토큰은 백엔드에서 암호화해 저장하고 프론트 응답·로그에 넣지 않는다.

### 4.2 갱신·로그아웃

설계 제안: 서비스 리프레시 토큰은 HttpOnly 쿠키로 전달한다. Bearer 방식은 일반 API의 액세스 토큰 전달 방식이며 이 쿠키와 함께 사용할 수 있다.

| 요청 | 동작 | 응답 |
|---|---|---|
| `GET /auth/me` | 현재 세션·사용자 확인 | 200, 로그인 응답의 user/profile_completed/calendar_connected |
| `POST /auth/refresh` | 쿠키 토큰 검증·회전, 이전 토큰 재사용 방지 | 200, access_token/token_type/expires_in + 새 쿠키 |
| `POST /auth/logout` | 현재 서비스 세션과 리프레시 토큰 폐기, 쿠키 삭제 | 204, body 없음 |

로그아웃은 만료된 액세스 토큰만 있어도 유효한 리프레시 세션으로 처리할 수 있게 한다. 이미 폐기된 세션은 쿠키를 지우고 204를 반환한다. 다른 기기의 모든 세션 종료는 이번 범위에 포함하지 않는다.

액세스 토큰에 세션 ID를 연결하고 보호 API에서 세션 폐기 여부를 확인해야 로그아웃 즉시 사용을 막을 수 있다. JWT 서명·만료만 검사하는 방식은 이 요구를 충족하지 않는다.

프론트는 `ACCESS_TOKEN_EXPIRED`일 때만 갱신을 한 번 시도한다. 갱신 실패 시 로그인으로 이동한다. 동시에 여러 요청이 만료되면 갱신 요청을 하나로 합친다. 쓰기 요청 재전송 시 원래 멱등 키를 유지한다.

리프레시 쿠키는 HttpOnly로 전달하고 만료기간은 30일로 둔다. 갱신할 때마다 새 리프레시 토큰과 함께 쿠키 만료도 30일 연장한다. DB의 로그인 세션에는 고정 만료일을 두지 않으며 로그아웃 또는 보안상 폐기 때 종료한다. 쿠키 사용 시 허용 Origin·credentials·CSRF 검증과 실제 사이트에 맞는 Secure/SameSite 설정을 적용한다. 서비스 로그아웃은 Google 계정 전체 로그아웃이나 이미 생성한 일정을 삭제하지 않는다.

## 5. 관심 분야·프로필·마이페이지

`GET /interest-categories` → 200 배열:

```json
[{"code": "20", "name": "정보통신"}, {"code": "19", "name": "전기·전자"}]
```

위 예시는 일부 항목이다. 실제 응답은 합의한 서비스 관심 분야 24개 전체를 코드 순으로 제공한다. 공식 NCS–자격증 분류 결과를 뜻하지 않는다. 이름을 DB 식별 키로 사용하지 않는다.

`GET /me/profile` → 200:

```json
{
  "profile": null,
  "profile_completed": false,
  "missing_fields": ["interest_category_codes", "education_level", "education_status", "has_career"],
  "profile_version": 0
}
```

최초 미입력은 404 대신 위 상태를 반환한다. `missing_fields`에는 관심 분야·최종 학력·졸업 상태·경력 유무 중 아직 입력하지 않은 필드가 표시된다.

| 필드 | 형식 | 규칙 |
|---|---|---|
| interest_category_codes | 문자열 배열 | 서비스 관심 분야 코드 `01`~`24` 중 정확히 1개 |
| education_level | 문자열 | 필수 enum: `high_school_or_below`, `college`, `university`, `graduate_school`, `other` |
| education_status | 문자열 | 필수 enum: `graduated`, `enrolled`, `expected`, `other` |
| major | 문자열 또는 null | 선택. 입력하지 않으면 null |
| has_career | Boolean | 경력 유무 필수 |
| career_years | 숫자 또는 null | 경력이 있으면 필수(0~80), 경력이 없으면 null |

`PATCH /me/profile`은 최초 저장과 마이페이지 수정을 공통 처리한다. 예시:

```json
{
  "profile_version": 0,
  "interest_category_codes": ["20"],
  "education_level": "university",
  "education_status": "graduated",
  "major": "컴퓨터공학",
  "has_career": false,
  "career_years": null
}
```

200은 GET과 같은 구조로 저장 결과와 증가한 버전을 반환한다. 생략 필드는 유지하고, null은 허용된 선택 필드만 삭제한다. 병합 결과를 검증하며 필수 누락은 422, 다른 탭이 먼저 수정한 버전은 409 `PROFILE_CHANGED`다. 프로필과 관심 분야 저장은 한 DB 트랜잭션으로 처리한다.

`missing_fields`는 폼 검증용이며 AI 추가 질문 흐름이 아니다. 마이페이지 수정은 저장된 프로필만 바꾸고 추천을 자동 실행하지 않는다. 추천은 화면의 추천 시작 동작으로 별도 요청한다.

## 6. 추천 생성

`POST /recommendations` · `Idempotency-Key: <새 UUID>`

```json
{}
```

서버가 현재 사용자의 저장 프로필을 읽는다. 요청으로 임의 사용자 프로필이나 모델명·프롬프트를 받지 않는다. 동기식으로 처리하며, 서버 실행 제한 시간과 프론트 타임아웃은 함께 설정한다. 시간 무제한 대기는 하지 않는다.

200 예시(필드 설명용이며 실제 추천 근거가 아님):

```json
{
  "status": "completed",
  "ordering": "llm_relevance",
  "selection_scope": "searched_candidates_only",
  "initial_display_count": 3,
  "total_count": 1,
  "items": [
    {
      "certificate_id": "33333333-3333-4333-8333-333333333333",
      "qnet_code": "1320",
      "name": "정보처리기사",
      "category": "T",
      "category_name": "국가기술자격",
      "summary": "공식 자료를 바탕으로 생성한 자격증 요약",
      "position": 1,
      "reason": "선택한 관심 분야와 연결되는 이유",
      "profile_factors": ["interest_category_codes"],
      "evidence": [{"document_id": "qnet-1320-1", "quote": "공식 원문에서 확인한 문장"}],
      "recommended_for": [{"text": "관련 업무에 관심 있는 분", "source_ids": ["qnet-1320-1"]}],
      "related_jobs": [{"name": "공식 자료로 확인한 관련 직무", "source_ids": ["qnet-1320-1"], "note": "공식 수행업무를 정리한 역할명입니다."}],
      "related_jobs_status": "available",
      "sources": [{"document_id": "qnet-1320-1", "source_url": "https://www.q-net.or.kr/crf005.do?id=crf00503&jmCd=1320", "retrieved_at": "2026-10-12T00:00:00Z", "evidence_scope": "공식 수행업무"}],
      "usage_restrictions": []
    }
  ]
}
```

- `items`는 0~10개이며 `total_count`와 길이가 같다. UI는 처음 `min(3, total_count)`개, 더보기 시 나머지를 표시한다.
- `position`은 LLM이 판단한 적합도 배열 순서(1~10)다. 점수나 취업 가능성 순위로 해석하지 않으며 순위 배지는 표시하지 않는다.
- T는 국가기술자격, S는 국가전문자격으로 표시한다.
- DB 후보 조회 → 필요 시 공식 근거 검색 → LLM 선택·설명 → Python 검증 → 저장·응답 순서다. 실제 후보 ID·종목 중복·개수·출처 연결을 검증한다.
- 요약·직업 근거가 없으면 null/빈 배열과 확인 필요 상태를 반환한다. 취업 보장이나 공식 근거 없는 응시 가능 확정 표현을 만들지 않는다.
- 공식 문서 RAG를 사용하면 문서명·URL·검색 근거를 내부에 보관하고 답변의 출처로 연결한다. 검색 실패를 정상 추천 성공으로 숨기지 않는다.
- 후보가 없으면 `status="no_results"`, `items=[]`, `total_count=0`으로 200을 반환한다. LLM/API 장애는 502/503/504로 구분한다.
- 도구 일시 실패는 최대 1회 재시도한다. 원래 정보가 없는 경우 같은 호출을 반복하지 않는다.
- 멱등 키 기반 재요청 처리는 API 설계 계약에 포함했지만, 현재 별도 추천 라우터에는 키 검증·실행 결과 영속 저장이 연결되지 않았다. 적용 시 같은 사용자·같은 키·같은 요청은 기존 결과를 돌려주고, 처리 중이면 409 `REQUEST_IN_PROGRESS`, 다른 요청이면 409 `IDEMPOTENCY_CONFLICT`를 반환한다. 이는 사용자용 재추천 기능이 아니다.
- 추천 실행 이력·결과 저장은 아직 구현되지 않았다. 이전 추천 목록 조회 API는 이번 범위에서 제공하지 않는다.

## 7. 기존 자격증·일정 조회

### 검색

`GET /certificates?q=정보처리&category=T&limit=20&offset=0`

| 쿼리 | 규칙 |
|---|---|
| q | 생략 시 빈 문자열, 최대 100자, 이름 또는 코드 검색 |
| category | 생략 가능, T/S로 제한하도록 보완 |
| limit | 기본 20, 1~100 |
| offset | 기본 0, 0 이상 |

200은 기존 배열을 유지한다. 항목은 `id`, `qnet_code`, `name`, `category`, `career_tags`, `description`, `source_url`, `last_synced_at`, `updated_at`이다. 관심 분야 추천과 단순 이름 검색은 별개다.

### 상세

`GET /certificates/{certificate_id}` → 200 기존 상세 구조 유지:

- 기본정보 + `exam_information.subjects`, `pass_criteria`, `fees`.
- 각각 `status`, `source_url`, `retrieved_at`, `phases`, 단계별 값이 있다.
- subjects의 written/practical/interview는 과목 배열, pass_criteria는 기준 문자열, fees는 원 단위 정수 또는 null이다.
- `data_status=complete/partial/unavailable`, `source_type=database/none`, `official_url`, `message`를 유지한다.
- 면접 유무는 확인된 시험 단계와 공식 근거로 표시한다. 면접 값 null만 보고 '면접 없음'으로 표시하지 않는다.
- 추천 카드의 AI 요약을 공식 시험과목·응시료 값에 덮어쓰지 않는다. RAG 보완 데이터가 필요해지면 공식 DB 값과 분리된 출처 필드를 설계한다.

### 일정

`GET /certificates/{certificate_id}/schedules?year=2026`

year는 필수, 1900~9999. 200은 단계별 행 배열이다. `id`, `certificate_id`, `year`, `round_key`, `round_label`, `phase`, `registration_start/end`, `registration_periods`, `exam_start/end`, `result_date`, `result_display_end`, `vacancy_registration_start/end`, `exam_site`, `source_url`, `last_synced_at`, `updated_at`을 유지한다.

- 하나의 회차에 필기·실기 등 여러 schedule_id가 존재할 수 있다. 화면에서 회차로 묶되 원본 ID를 보존한다.
- `registration_periods`가 분리되어 있으면 그 기간들만 접수 기간이다. 전체 시작~끝을 연속 접수로 표시하지 않는다.
- 일정 없음은 빈 배열이며, 미시행 확정이 아니라 저장된 일정 없음이다.
- 현재 구현은 존재하지 않는 자격증의 일정도 빈 배열일 수 있다. 계약상 404로 구분하도록 종목 존재 검사를 추가한다.
- 사용자가 회차를 선택하는 단계에서는 DB에 user_exam_plans를 만들지 않는다.

## 8. Calendar 직접 등록

`POST /calendar/register` · `Idempotency-Key: <새 UUID>`

사용자가 시험회차와 등록 항목을 선택한 뒤 등록 버튼을 누르면 바로 호출한다. 별도 미리보기 화면·API·토큰은 사용하지 않는다.

```json
{
  "certificate_id": "33333333-3333-4333-8333-333333333333",
  "schedule_ids": ["44444444-4444-4444-8444-444444444444"],
  "schedule_versions": {"44444444-4444-4444-8444-444444444444": "2026-10-08T06:00:00Z"},
  "event_types": ["registration", "written_exam", "practical_exam", "result"]
}
```

| 요청 필드 | 계약 |
|---|---|
| certificate_id | 선택한 자격증 UUID |
| schedule_ids | 선택 회차의 단계별 일정 UUID 배열, 1~6개, 중복 불가 |
| schedule_versions | 각 일정 ID와 일정 조회 응답의 updated_at. 선택한 일정 ID와 키 집합이 같아야 함 |
| event_types | 사용자가 화면에서 선택한 네 종류 중 최소 1개. 선택하지 않은 종류는 자동 등록하지 않으며 중복 불가 |
| Idempotency-Key | 하나의 등록 작업을 식별하는 UUID 헤더. 통신 재시도 시 동일 키 유지 |

서버가 DB에서 날짜·제목·공식 출처를 가져온다. `event_types`에는 화면에서 사용자가 고른 종류만 보낸다. 사용자 세션, Google 권한, 같은 종목·연도·회차의 일정인지, 날짜 순서·경계·출처·중복을 검사한다. 다른 캘린더 ID나 임의 제목·날짜는 받지 않는다. 선택 화면에서 읽은 일정 버전이 달라졌으면 신규 등록을 409 `SCHEDULE_CHANGED`로 거절하고 일정을 다시 조회·선택하도록 안내한다.

| 종류 | 변환 규칙 |
|---|---|
| registration | 각 실제 접수 구간마다 이벤트. 필기/실기 접수 구분을 제목에 표시 |
| written_exam | phase=written인 공식 시험 기간 |
| practical_exam | phase=practical인 공식 시험 기간 |
| result | 각 선택 단계의 result_date 하루. result_display_end를 발표 기간으로 사용하지 않음 |

네 종류는 이벤트 수 네 개 보장을 뜻하지 않는다. 접수 구간·발표 단계에 따라 여러 이벤트가 생길 수 있다. 면접·1차·2차를 임의로 필기·실기로 변환하지 않는다. 날짜나 공식 출처가 누락·모순된 접수 구간은 생성하지 않고 구간별 사유와 `schedule_id`, 1부터 시작하는 `period_index`를 반환한다. DB에 접수 구간 행 자체가 없으면 해당 `schedule_id`와 `period_index: null`을 반환한다. 다른 종류의 일정이 누락된 경우에는 해당 `event_type`과 사유를 반환한다. 등록 가능한 항목이 하나도 없으면 422 `NO_REGISTERABLE_EVENTS`다.

날짜만 있는 일정은 종일 이벤트다. DB의 포함 종료일을 Google end.date에는 다음 날로 변환한다. 공식 시험 기간을 사용자의 개인 확정 시험일로 표현하지 않는다. 분리된 registration_periods 사이 날짜를 접수 기간에 포함하지 않는다.

200 예시:

```json
{
  "registration_id": "55555555-5555-4555-8555-555555555555",
  "status": "partial",
  "items": [
    {"item_key": "written-registration-2026-01-05-2026-01-08", "event_type": "registration", "status": "created", "google_event_id": "provider-event-id", "html_link": "https://calendar.google.com/"}
  ],
  "excluded_items": [{"event_type": "practical_exam", "reason": "선택한 일정에서 실기 날짜를 확인할 수 없습니다.", "schedule_id": null, "period_index": null}],
  "message": "확인 가능한 일정을 등록했습니다. 등록하지 못한 항목을 확인해주세요."
}
```

- 전체 status: `completed`, `partial`, `failed`, `pending_confirmation`. 요청한 항목 일부 제외·실패는 partial, 결과 불명은 pending_confirmation으로 표시한다.
- 항목 status: `created`, `already_registered`, `failed`, `unknown`. 실패 항목에는 code/message/retryable을 덧붙인다.
- 등록 작업이 접수되어 항목별 결과를 얻었으면 HTTP 200 + 위 결과로 반환한다. 인증·입력·DB 사전 검사 실패는 공통 오류 HTTP 상태를 사용한다. 프론트는 HTTP 200만 보고 전체 성공 안내를 하지 않는다.
- 회차 선택 단계에는 저장하지 않는다. 등록 요청 때 user_exam_plans와 대기 작업을 먼저 저장하고 Google 호출 결과를 항목별 기록한다. 외부 호출 중 DB 트랜잭션을 길게 잡지 않는다.
- 사용자·종목·회차·단계·event_type·접수구간을 포함한 정규화된 중복 키에 DB UNIQUE 제약을 둔다. 같은 멱등 키의 다른 payload는 409 `IDEMPOTENCY_CONFLICT`다.
- 인증·소유권 확인 뒤 기존 멱등 작업을 먼저 조회한다. 기존 결과 반환·Google 생성 여부 확인은 최초 등록 스냅샷으로 처리한다. 신규 작업에만 일정 버전 사전 검사를 적용한다.
- Google 생성 후 응답 또는 DB 기록이 실패할 수 있다. 재시도에도 같은 결정적 Google 이벤트 ID를 사용하고 Google 조회로 존재 여부를 확인한다. unknown 항목은 존재 여부를 확인하기 전까지 새 작업에서도 생성하지 않는다.
- 같은 요청 재전송은 성공 항목을 재생성하지 않고 미확정·재시도 가능한 실패 항목만 복구한다. 아직 생성되지 않은 항목의 공식 일정이 변경되었다면 `SCHEDULE_CHANGED` 항목 오류로 멈춘다. 사용자가 최신 일정을 다시 선택하고 새 키로 요청해도 기존 성공 이벤트는 공통 중복 키로 제외한다.
- 등록 상태 조회용 별도 화면/API 대신 같은 키의 재요청 응답을 이용한다. 수정·삭제·Google에서 사용자가 변경한 내용의 동기화는 제공하지 않는다. 과거 등록 기록만으로 현재 Google 일정 상태를 보장하거나 삭제된 이벤트를 자동 재생성하지 않는다.

## 9. DB 및 Agent 연결

| 저장소 | API에서의 역할 / 필요한 조정 |
|---|---|
| users | Google 사용자 식별. 기존 provider+subject 고유성 유지 |
| user_profiles | 프로필 저장·수정. 별도 SQL로 `interest_category_code`, `career_years`, `profile_version` 추가 준비됨. 공용 DB에는 미적용 |
| recommendation_interest_categories | 24개 서비스 관심 분야 코드 목록. 사용자 선택은 현재 `user_profiles.interest_category_code` FK 하나에 저장 |
| certificates / exam_information / schedules | 기존 공식 데이터 재사용, 추천·상세·Calendar의 근거 |
| sources | 공식 수집 원본·상태. 실제 복합 PK `(source_key, retrieved_at)` 유지 |
| recommendation_sessions / results | API 설계상 프로필 스냅샷·실행 상태·최대 10개 결과 저장 대상. 별도 라우터의 현재 구현은 영속 실행 기록·멱등 저장을 아직 연결하지 않음 |
| ai_logs | 모델·도구·검증 결과·시간·토큰 수. 비밀 토큰과 모델의 내부 사고 과정은 저장하지 않음 |
| user_exam_plans / calendar_registrations / calendar_events | Calendar 등록 시 생성, 요청 멱등 키·사용자 선택·항목별 Google ID·처리 상태 저장. `backend/db/calendar_registration.sql` 적용 필요 |
| 인증 세션·Google 권한 저장소 | 서비스 리프레시 토큰 해시·폐기 정보와 암호화된 Google 자격증명 분리 보관 필요 |
| 멱등 처리 저장소 | 사용자·작업·키·요청 해시·진행 상태·결과 저장. 실행 세션 테이블 활용 가능 |

사용자가 제공한 ERD의 모든 테이블이 현재 구현되어 있다는 뜻은 아니다. `recommendation_answers`는 추가 질문을 제거했으므로 구현하지 않는다. Calendar 등록은 종일 일정의 날짜 범위와 중복 키를 별도 등록 테이블에 저장한다.

추천 내부 흐름:

```text
인증·필수 입력 검증 → 저장 프로필 스냅샷 → DB 후보 탐색
→ LLM 도구 선택 / Python 도구 실행 → 필요 시 공식 문서 검색
→ 후보·출처·개수 검증 → 오류 시 제한된 재시도 또는 실패 안내
→ 결과 저장 → 최대 10개 응답 → 화면에서 3개 먼저 표시
```

Calendar 등록은 사용자 명시적 확인을 거친 별도 쓰기 API다. 추천 Agent의 판단만으로 실행하지 않는다. LangChain은 도구 연결, LangGraph는 상태·분기·재시도 관리에 사용하며 공통 조회 함수는 재사용한다.

## 10. 담당자 간 연결 지점

| 담당 | 공유 계약 |
|---|---|
| Google 로그인 담당 | 사용자 UUID, Bearer 검증 함수, 세션 폐기, Google 권한/토큰 저장·갱신 함수 |
| Google Calendar 담당 | 로그인 담당의 현재 사용자·Google 토큰 제공 함수를 사용. 독자적인 로그인 테이블을 중복 생성하지 않음 |
| 프로필·추천 담당 | 저장 프로필 버전, 추천 결과 카드 구조, 공식 종목 UUID 및 출처 |
| 프론트 담당 | 폼 검증·로딩·더보기·부분 정보 안내·등록 버튼 처리·부분 실패 표시 |

업무별 라우터를 분리하되 `/auth`, `/me`, `/recommendations`, `/certificates`, `/calendar`와 공통 오류·인증 규격은 공유한다. 문서만 보고 Google 권한 연결이 실제 구현됐다고 가정하지 않는다.

## 11. 인수 확인 목록

| 상황 | 기대 결과 |
|---|---|
| 토큰 없이 보호 API 호출 | 401 |
| 30분 만료 후 갱신 | 새 액세스 토큰, 이전 리프레시 재사용 차단 |
| 로그아웃 후 기존 액세스 토큰 사용 | 즉시 401 |
| 필수 프로필 누락 | 422, 추가 질문 Agent 실행 없음 |
| 경력 분야 미입력 | 다른 필수 조건 충족 시 저장·추천 가능 |
| 후보 0/1/2/3/10개 | 개수 그대로 표시, 최대 10개, LLM 적합도 순서 유지 |
| 더보기 클릭 | 기존 응답 확장, 추가 추천 호출 없음 |
| LLM에 없는 종목·근거가 섞임 | 검증·제한 재시도 또는 실패/확인 필요 |
| 응시료·면접 정보 null | 무료·면접 없음으로 오표시하지 않음 |
| 분리된 접수 기간 | 구간별 표시·등록, 중간 날짜 포함하지 않음 |
| 회차 선택만 함 | 사용자 시험 계획 저장 없음 |
| Calendar 권한 거절 | 로그인 상태 구분, 등록 403 |
| 일정 선택 후 원본 일정 변경 | 등록 409 SCHEDULE_CHANGED, 일정 다시 조회·선택 |
| 등록 버튼 중복 클릭·통신 재전송 | 같은 일정 중복 생성 없음 |
| 일부 Google 요청 실패 | 성공 유지, 항목별 실패·불명 상태 안내 |
| Google 성공 후 DB 기록 실패 | 같은 외부 ID 조회로 복구, 새 이벤트 무조건 생성 금지 |
| 마이페이지 수정 | 프로필만 변경, 자동 추천·일정 수정 없음 |

## 12. 구현 전에 마지막으로 확정할 항목

제품 범위를 다시 논의할 필요는 없지만 아래 값은 최종 화면 확인 또는 담당자 합의가 필요하다.

| 항목 | 현재 문서 처리 |
|---|---|
| 최종 Figma의 입력 항목·버튼 매핑 | 입력 필수 규칙은 이 문서에 반영. 최종 화면의 세부 버튼·응답 표시만 구현 전 대조 |
| 추천 실행 제한 시간·멱등 결과 보존 기간 | 동기 응답은 확정. API 구현에 멱등 키 처리를 연결하고 실행 시간·결과 보존 값은 담당자 합의 필요 |
| 과거 날짜와 면접·1차·2차 일정 | Calendar 등록 대상은 접수·필기·실기·합격발표 4종. 과거 항목 선택 허용 정책은 화면과 대조 필요 |
| Calendar 권한 오류 | 저장된 권한·갱신 토큰이 없거나 갱신 과정에서 권한 철회가 확인되면 403 `GOOGLE_CALENDAR_PERMISSION_REQUIRED`를 반환한다. 이벤트 요청 중 발생한 Google 오류는 항목별 실패로 응답한다. |

## 참고

- [최종 Figma 대상](https://www.figma.com/design/D2HXzNakaFEjnYRe05ghuP/?node-id=88-3) — 이번 작성 시 직접 검증하지 못함.
- [Google 서버 OAuth 안내](https://developers.google.com/identity/protocols/oauth2/web-server) — 코드 교환·state·권한·갱신.
- [Google Calendar 이벤트 생성](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert) — primary 캘린더 대상 이벤트 추가.
- [Google Calendar 이벤트 리소스](https://developers.google.com/workspace/calendar/api/v3/reference/events) — 종일 날짜와 종료일·이벤트 ID.
- 현행 구현: `backend/main.py`, `backend/schemas.py`, `backend/exam_schemas.py`, `backend/db/schema.sql`.

이 문서는 현재 회의 결정과 구현된 API 계약을 반영한다. 이전 PRD·팀 공유문서의 추가 질문, 순위 Top 3, 별도 Calendar 연결·내역, 비동기 Agent 상태 조회가 이 문서와 다르면 이 문서의 범위를 적용한다. Calendar 등록에 필요한 SQL은 실제 DB에 적용한 상태가 아니다.

