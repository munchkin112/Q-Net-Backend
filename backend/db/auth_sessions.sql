-- 우리 서비스의 로그인 세션과 리프레시 토큰 사용 기록을 저장한다.
-- 기존 users 테이블이 필요하다.
-- 실제 적용 시에는 두 테이블과 인덱스를 하나의 트랜잭션에서 생성한다.


-- 로그인 한 번마다 생성하는 세션이다.
-- 액세스 토큰의 sid에는 이 테이블의 id가 들어간다.
CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,

    CHECK (expires_at > created_at),
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