-- 앱 로그인 기반 캘린더 테이블을 앱 로그인 없는 Calendar 연결 구조로 전환한다.
-- Render DB의 현재 구조에서는 calendar_registrations / calendar_events가 구버전이다.
-- 두 테이블이 비어 있을 때만 이름을 바꿔 보존하고 새 테이블을 만든다.
-- 행이 있거나 예상하지 못한 구조면 전체 작업을 중단한다.
-- 대상 DB가 개발용인지 확인하고, 기존 앱 코드와 적용 순서를 조정한 뒤 실행한다.

BEGIN;

DO $migration$
DECLARE
    current_table text;
    legacy_table text;
    has_user_id boolean;
    has_connection_id boolean;
    row_count bigint;
    old_index record;
    legacy_index text;
BEGIN
    IF to_regclass('public.certificates') IS NULL
       OR to_regclass('public.schedules') IS NULL THEN
        RAISE EXCEPTION 'certificates와 schedules 테이블이 먼저 있어야 합니다.';
    END IF;

    FOREACH current_table IN ARRAY ARRAY[
        'calendar_registrations',
        'calendar_events'
    ] LOOP
        legacy_table := current_table || '_legacy_login_20261012';

        IF to_regclass(format('public.%I', current_table)) IS NULL THEN
            IF to_regclass(format('public.%I', legacy_table)) IS NOT NULL THEN
                RAISE EXCEPTION '%, 이전 테이블만 남아 있습니다. 수동 확인이 필요합니다.', current_table;
            END IF;
            CONTINUE;
        END IF;

        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = current_table
              AND column_name = 'user_id'
        ) INTO has_user_id;

        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = current_table
              AND column_name = 'calendar_connection_id'
        ) INTO has_connection_id;

        IF has_user_id AND NOT has_connection_id THEN
            IF to_regclass(format('public.%I', legacy_table)) IS NOT NULL THEN
                RAISE EXCEPTION '보존용 테이블 %가 이미 있습니다. 중복 마이그레이션인지 확인해주세요.', legacy_table;
            END IF;

            EXECUTE format('SELECT count(*) FROM public.%I', current_table)
                INTO row_count;
            IF row_count > 0 THEN
                RAISE EXCEPTION '%.% 행이 있어 자동 전환을 중단했습니다. 기존 데이터를 먼저 확인해주세요.', current_table, row_count;
            END IF;

            EXECUTE format(
                'ALTER TABLE public.%I RENAME TO %I',
                current_table,
                legacy_table
            );

            -- 기존 인덱스 이름을 비워 새 테이블의 기본·고유 인덱스와 충돌하지 않게 한다.
            FOR old_index IN
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = legacy_table
            LOOP
                legacy_index := left('legacy_login_20261012_' || old_index.indexname, 63);
                IF EXISTS (
                    SELECT 1
                    FROM pg_class AS relation
                    JOIN pg_namespace AS schema_name ON schema_name.oid = relation.relnamespace
                    WHERE schema_name.nspname = 'public'
                      AND relation.relname = legacy_index
                ) THEN
                    RAISE EXCEPTION '보존용 인덱스 이름 %가 이미 있습니다.', legacy_index;
                END IF;
                EXECUTE format(
                    'ALTER INDEX public.%I RENAME TO %I',
                    old_index.indexname,
                    legacy_index
                );
            END LOOP;
        ELSIF has_connection_id AND NOT has_user_id THEN
            -- 이미 새 구조인 테이블은 그대로 둔다.
            NULL;
        ELSE
            RAISE EXCEPTION '%. 테이블 구조가 예상과 달라 자동 전환을 중단했습니다.', current_table;
        END IF;
    END LOOP;
END
$migration$;

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
    google_event_id text NOT NULL UNIQUE CHECK (google_event_id ~ '^[a-v0-9]{5,1024}$'),
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

DO $verification$
DECLARE
    required_table text;
BEGIN
    FOREACH required_table IN ARRAY ARRAY[
        'calendar_connections',
        'calendar_exam_plans',
        'calendar_registrations',
        'calendar_events'
    ] LOOP
        IF to_regclass(format('public.%I', required_table)) IS NULL THEN
            RAISE EXCEPTION '필수 캘린더 테이블 % 생성에 실패했습니다.', required_table;
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'calendar_registrations'
          AND column_name = 'calendar_connection_id'
    ) OR NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'calendar_events'
          AND column_name = 'calendar_connection_id'
    ) THEN
        RAISE EXCEPTION '새 캘린더 연결 컬럼을 확인하지 못했습니다.';
    END IF;
END
$verification$;

COMMIT;

