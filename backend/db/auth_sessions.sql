-- 이전 앱 로그인 구현의 세션 테이블이다. 현재 API에서 로그인은 사용하지 않으므로 새로 적용하지 않는다.
-- Calendar 전용 브라우저 연결은 calendar_registration.sql의 calendar_connections를 사용한다.


-- 로그인 한 번마다 생성하는 세션이다.
-- expires_at은 NULL이면 정해진 만료 없이 유지하며, 로그아웃·보안 폐기로 종료한다.
-- 액세스 토큰의 sid에는 이 테이블의 id가 들어간다.
CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    revoked_at timestamptz,

    CHECK (expires_at IS NULL OR expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX auth_sessions_user_id_idx
    ON auth_sessions (user_id);


-- 우리 서비스 리프레시 토큰의 원본 대신 SHA-256 해시를 저장한다.
-- 사용한 토큰의 기록도 보관하여 이전 토큰의 재사용을 감지한다.
-- 만료와 로그아웃 여부는 연결된 auth_sessions에서 확인한다.
CREATE TABLE auth_refresh_tokens (
    token_hash text PRIMARY KEY,
    session_id uuid NOT NULL
        REFERENCES auth_sessions(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    used_at timestamptz,

    CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CHECK (used_at IS NULL OR used_at >= created_at)
);

CREATE INDEX auth_refresh_tokens_session_id_idx
    ON auth_refresh_tokens (session_id);


-- 한 로그인 세션에는 아직 사용하지 않은 리프레시 토큰을
-- 최대 하나만 허용한다.
CREATE UNIQUE INDEX auth_refresh_tokens_one_unused_per_session_idx
    ON auth_refresh_tokens (session_id)
    WHERE used_at IS NULL;

