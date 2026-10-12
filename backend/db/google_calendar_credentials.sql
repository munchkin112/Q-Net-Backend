-- 이전 앱 로그인 방식에서 사용하던 보관 테이블이다. 현재 API에서는 사용하지 않으며 새로 적용하지 않는다.
-- Calendar 전용 연결은 calendar_registration.sql의 calendar_connections를 사용한다.
CREATE TABLE IF NOT EXISTS google_calendar_credentials (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_ciphertext text NOT NULL
        CHECK (btrim(refresh_token_ciphertext) <> ''),
    scopes text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

