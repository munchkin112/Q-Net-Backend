# Google 로그인 연동 메모

이 문서는 `feature/google-auth`의 인증 코드와 다른 담당자의 작업을 연결할 때 확인할 사항이다. 실제 비밀키·토큰 값은 이 파일이나 Git에 넣지 않는다.

## 현재 API 흐름

1. 프론트가 `GET /auth/google/authorize`를 호출한다. 브라우저는 5분짜리 HttpOnly OAuth 확인 쿠키를 받고, 응답의 `authorization_url`로 이동한다.
2. Google이 등록된 `GOOGLE_REDIRECT_URI`로 `code`와 `state`를 보낸다. 프론트는 쿠키를 포함해 `POST /auth/google`에 두 값을 전달한다.
3. 백엔드는 state·Google ID 토큰을 검증하고 Google `sub`로 사용자를 찾거나 만든다. 동일 DB 트랜잭션에서 Calendar 자격 증명 저장 함수, 서비스 세션, 리프레시 토큰 해시를 저장한다.
4. 로그인 응답의 **서비스 액세스 토큰**은 보호 API에 `Authorization: Bearer <token>`으로 전달한다. **서비스 리프레시 토큰**은 응답 JSON이 아닌 HttpOnly 쿠키에만 있다. Google 토큰은 프론트에 반환하지 않는다.
5. 액세스 토큰이 만료되면 허용된 Origin에서 `POST /auth/refresh`로 갱신한다. `POST /auth/logout`은 DB 세션을 폐기하고 리프레시 쿠키를 지운다. 보호 API는 `Depends(get_current_user)`로 폐기 여부까지 확인한다.

## 담당자 사이의 연결 계약

- Calendar 파일은 이 브랜치에서 만들지 않는다. 로그인 코드가 `backend.calendar_service.create_google_calendar_credential(connection, user_id, refresh_token: str | None, scopes: str) -> bool`을 호출한다. 함수 내부에서 Google refresh token을 암호화하고, `None`이면 기존 토큰을 보존한다. 커밋은 로그인 코드가 담당한다. 함수가 없으면 Google code를 교환하기 전에 503을 반환한다.
- `backend/main.py` 통합은 백엔드 담당자가 맡는다. 이 브랜치의 인증 라우터와 `AuthRequestError` 처리기, `AUTH_ALLOWED_ORIGINS` 기반 CORS가 유지되는지 병합 후 확인한다.
- `GET /auth/me` 응답의 `profile_completed`는 필수 관심 분야 저장 방식이 정해져야 계산할 수 있다. 현재 DB의 `user_profiles`에는 `interest_category_codes`가 없으므로 로그인 응답은 보수적으로 `false`를 반환한다. `calendar_connected`의 재조회는 Calendar 저장소의 조회 함수가 필요하다. 두 값을 임의로 추정하지 않기 위해 `/auth/me`는 아직 추가하지 않았다.
- 프론트와 백엔드가 다른 사이트에 배포되면 OAuth 확인 쿠키와 리프레시 쿠키의 `SameSite`/`Secure`, 브라우저의 `credentials` 전달을 실제 배포 주소에서 검증해야 한다. 현재 코드는 `SameSite=Lax`이며 단일 서버 모의 테스트만 통과했다. 여러 서버 프로세스를 쓰면 메모리에 보관하는 OAuth state가 공유되지 않으므로 별도 저장소가 필요하다.
- 서비스 세션은 정해진 서버 만료시각 없이 유지하고, 로그아웃 또는 보안상 폐기 때 종료한다. 리프레시 쿠키는 만료일을 지정하지 않는 브라우저 세션 쿠키다. 브라우저가 세션 쿠키를 종료 시 삭제하는 방식이면 다시 로그인해야 할 수 있다.

## 설정과 DB 점검

- 필요한 변수 이름과 설명은 `backend/.env.example`에 있다. 실제 값은 로컬 `backend/.env` 또는 배포 환경변수에만 둔다.
- DB 담당자가 세션 정책을 확정한 뒤 `backend/db/auth_sessions.sql`을 검토·적용한다. 기존 DB에 적용됐다고 가정하지 않는다.
- 저장소 최상위에서 `python -m backend.db.check_auth`를 실행하면 설정 유무, 연결 여부, `users`·`auth_sessions`·`auth_refresh_tokens`의 존재 여부를 읽기 전용으로 확인한다. DB URL이나 오류의 비밀값은 출력하지 않는다.
- `python -m unittest backend.tests.test_google_auth backend.tests.test_auth_contract backend.tests.test_auth_database_check -q`로 외부 Google/DB 호출 없는 인증 테스트를 실행한다. 실제 Google 로그인 → 실제 DB 저장 → Calendar 동의 → 갱신·로그아웃의 통합 테스트는 Calendar 함수·DB 테이블·배포 주소 준비 후 별도로 수행한다.
