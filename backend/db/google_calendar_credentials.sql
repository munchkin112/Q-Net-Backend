-- Google OAuth 갱신 토큰을 암호문으로 저장한다.
-- 먼저 users 테이블이 생성되어 있어야 한다.
-- 실제 DB에는 대상 환경을 확인한 뒤 별도로 적용한다.
CREATE TABLE IF NOT EXISTS google_calendar_credentials (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_ciphertext text NOT NULL
        CHECK (btrim(refresh_token_ciphertext) <> ''),
    scopes text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
