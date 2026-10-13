-- 앱 로그인 없이 Calendar 전용 Google 권한과 선택 일정을 저장한다.
-- certificates, schedules 테이블이 먼저 필요하다.
-- 대상 DB를 확인한 뒤 개발 환경에 적용한다. 이 파일은 코드에서 자동 실행하지 않는다.

CREATE TABLE IF NOT EXISTS calendar_connections (
    id uuid PRIMARY KEY,
    session_token_hash text NOT NULL UNIQUE
        CHECK (session_token_hash ~ '^[0-9a-f]{64}$'),
    refresh_token_ciphertext text NOT NULL
        CHECK (btrim(refresh_token_ciphertext) <> ''),
    scopes text NOT NULL CHECK (btrim(scopes) <> ''),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE INDEX IF NOT EXISTS calendar_connections_expires_idx
    ON calendar_connections(expires_at);

CREATE TABLE IF NOT EXISTS calendar_exam_plans (
    id uuid PRIMARY KEY,
    calendar_connection_id uuid NOT NULL
        REFERENCES calendar_connections(id) ON DELETE CASCADE,
    certificate_id uuid NOT NULL REFERENCES certificates(id) ON DELETE RESTRICT,
    year smallint NOT NULL CHECK (year BETWEEN 1900 AND 9999),
    round_key text NOT NULL CHECK (btrim(round_key) <> ''),
    round_label text NOT NULL CHECK (btrim(round_label) <> ''),
    selected_event_types jsonb NOT NULL
        CHECK (jsonb_typeof(selected_event_types) = 'array'),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'partial', 'failed', 'pending_confirmation')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (calendar_connection_id, certificate_id, year, round_key)
);

CREATE TABLE IF NOT EXISTS calendar_registrations (
    id uuid PRIMARY KEY,
    calendar_connection_id uuid NOT NULL
        REFERENCES calendar_connections(id) ON DELETE CASCADE,
    idempotency_key uuid NOT NULL,
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    exam_plan_id uuid NOT NULL REFERENCES calendar_exam_plans(id) ON DELETE CASCADE,
    request_events jsonb NOT NULL CHECK (jsonb_typeof(request_events) = 'array'),
    excluded_items jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(excluded_items) = 'array'),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'partial', 'failed', 'pending_confirmation')),
    response jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (calendar_connection_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id uuid PRIMARY KEY,
    exam_plan_id uuid NOT NULL REFERENCES calendar_exam_plans(id) ON DELETE CASCADE,
    registration_id uuid NOT NULL REFERENCES calendar_registrations(id) ON DELETE CASCADE,
    calendar_connection_id uuid NOT NULL
        REFERENCES calendar_connections(id) ON DELETE CASCADE,
    certificate_id uuid NOT NULL REFERENCES certificates(id) ON DELETE RESTRICT,
    schedule_id uuid NOT NULL REFERENCES schedules(id) ON DELETE RESTRICT,
    item_key text NOT NULL CHECK (btrim(item_key) <> ''),
    event_type text NOT NULL
        CHECK (event_type IN ('registration', 'written_exam', 'practical_exam', 'result')),
    phase text NOT NULL,
    starts_on date NOT NULL,
    ends_on date NOT NULL CHECK (ends_on >= starts_on),
    title text NOT NULL CHECK (btrim(title) <> ''),
    description text NOT NULL,
    source_url text NOT NULL CHECK (source_url ~ '^https?://'),
    schedule_version timestamptz NOT NULL,
    google_event_id text NOT NULL UNIQUE CHECK (length(google_event_id) BETWEEN 5 AND 1024 AND google_event_id ~ '^[a-v0-9]+$'),
    html_link text,
    sync_status text NOT NULL DEFAULT 'pending'
        CHECK (sync_status IN ('pending', 'created', 'failed', 'unknown')),
    error_code text,
    error_message text,
    retryable boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (calendar_connection_id, schedule_id, item_key)
);

CREATE INDEX IF NOT EXISTS calendar_events_plan_idx ON calendar_events(exam_plan_id);
CREATE INDEX IF NOT EXISTS calendar_registrations_connection_created_idx
    ON calendar_registrations(calendar_connection_id, created_at DESC);

