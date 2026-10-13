# 인증 구현 상태

2026-10-12 결정으로 **앱 Google 로그인과 서비스 Bearer 세션은 현재 API에서 사용하지 않는다.** 이 파일의 이전 로그인 연동 안내는 더 이상 현재 계약이 아니다.

현재 흐름은 다음과 같다.

- 자격증 검색·추천은 공개 API다.
- 프로필은 프론트 브라우저가 보관하고 `POST /recommendations` 요청 본문에 포함한다.
- Google Calendar는 일정 등록 시 별도 OAuth 동의를 받는다. 관련 경로는 `GET /calendar/google/authorize`, `POST /calendar/google/callback`, `POST /calendar/register`다.
- Calendar 전용 세션은 HttpOnly 쿠키이며 30일 만료다. Google refresh token은 암호화하고 세션 쿠키 원문은 해시해 저장한다.
- 앱 로그인 라우터는 `backend/main.py`에 등록하지 않는다. `auth_*` 파일과 `auth_sessions.sql`은 이전 구현 자료로 남아 있으며 현재 서비스 흐름에서 호출하지 않는다.

현재 계약과 프론트 연결 방법은 [API 설계서](../docs/API_설계서.md)를 확인한다. Calendar 연결 테이블은 `backend/db/calendar_registration.sql`을 대상 개발 DB인지 확인한 뒤 적용해야 한다. 실제 DB에 자동 적용하지 않는다.

