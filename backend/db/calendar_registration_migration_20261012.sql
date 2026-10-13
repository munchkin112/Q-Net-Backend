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
    column_count integer;
    unexpected_column boolean;
    expected_columns text[];
    expected_types text[];
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
            -- 잠금 후 알려진 구버전 구조인지 확인하고, 동시에 쓰기가 생기지 않게 한다.
            EXECUTE format('LOCK TABLE public.%I IN ACCESS EXCLUSIVE MODE', current_table);

            IF current_table = 'calendar_registrations' THEN
                expected_columns := ARRAY[
                    'id', 'user_id', 'idempotency_key', 'request_hash', 'exam_plan_id',
                    'request_events', 'excluded_items', 'status', 'response', 'created_at', 'updated_at'
                ];
                expected_types := ARRAY[
                    'uuid', 'uuid', 'uuid', 'text', 'uuid', 'jsonb', 'jsonb', 'text',
                    'jsonb', 'timestamptz', 'timestamptz'
                ];
            ELSE
                expected_columns := ARRAY[
                    'id', 'exam_plan_id', 'registration_id', 'user_id', 'certificate_id',
                    'schedule_id', 'item_key', 'event_type', 'phase', 'starts_on', 'ends_on',
                    'title', 'description', 'source_url', 'schedule_version', 'google_event_id',
                    'html_link', 'sync_status', 'error_code', 'error_message', 'retryable',
                    'created_at', 'updated_at'
                ];
                expected_types := ARRAY[
                    'uuid', 'uuid', 'uuid', 'uuid', 'uuid', 'uuid', 'text', 'text', 'text',
                    'date', 'date', 'text', 'text', 'text', 'timestamptz', 'text', 'text',
                    'text', 'text', 'text', 'bool', 'timestamptz', 'timestamptz'
                ];
            END IF;

            SELECT count(*) INTO column_count
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = current_table;

            SELECT EXISTS (
                SELECT 1
                FROM unnest(expected_columns, expected_types) AS expected(column_name, udt_name)
                LEFT JOIN information_schema.columns AS actual
                  ON actual.table_schema = 'public'
                 AND actual.table_name = current_table
                 AND actual.column_name = expected.column_name
                 AND actual.udt_name = expected.udt_name
                WHERE actual.column_name IS NULL
            ) INTO unexpected_column;

            IF column_count <> cardinality(expected_columns) OR unexpected_column THEN
                RAISE EXCEPTION '%. 구버전으로 확인된 테이블 구조와 달라 자동 전환을 중단했습니다.', current_table;
            END IF;

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

DO $verification$
DECLARE
    required_table text;
    column_count integer;
    expected_constraint_counts integer[];
    actual_constraint_counts integer[];
    unexpected_column boolean;
    expected_columns text[];
    expected_types text[];
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

    -- IF NOT EXISTS가 기존의 불완전한 테이블을 조용히 통과시키지 않게
    -- 네 테이블의 컬럼·자료형·제약조건 수를 확인한다.
    FOREACH required_table IN ARRAY ARRAY[
        'calendar_connections',
        'calendar_exam_plans',
        'calendar_registrations',
        'calendar_events'
    ] LOOP
        IF required_table = 'calendar_connections' THEN
            expected_columns := ARRAY[
                'id', 'session_token_hash', 'refresh_token_ciphertext', 'scopes',
                'expires_at', 'revoked_at', 'created_at', 'updated_at'
            ];
            expected_types := ARRAY[
                'uuid', 'text', 'text', 'text', 'timestamptz', 'timestamptz',
                'timestamptz', 'timestamptz'
            ];
            expected_constraint_counts := ARRAY[1, 1, 5, 0];
        ELSIF required_table = 'calendar_exam_plans' THEN
            expected_columns := ARRAY[
                'id', 'calendar_connection_id', 'certificate_id', 'year', 'round_key',
                'round_label', 'selected_event_types', 'status', 'created_at', 'updated_at'
            ];
            expected_types := ARRAY[
                'uuid', 'uuid', 'uuid', 'int2', 'text', 'text', 'jsonb', 'text',
                'timestamptz', 'timestamptz'
            ];
            expected_constraint_counts := ARRAY[1, 1, 5, 2];
        ELSIF required_table = 'calendar_registrations' THEN
            expected_columns := ARRAY[
                'id', 'calendar_connection_id', 'idempotency_key', 'request_hash',
                'exam_plan_id', 'request_events', 'excluded_items', 'status', 'response',
                'created_at', 'updated_at'
            ];
            expected_types := ARRAY[
                'uuid', 'uuid', 'uuid', 'text', 'uuid', 'jsonb', 'jsonb', 'text',
                'jsonb', 'timestamptz', 'timestamptz'
            ];
            expected_constraint_counts := ARRAY[1, 1, 4, 2];
        ELSE
            expected_columns := ARRAY[
                'id', 'exam_plan_id', 'registration_id', 'calendar_connection_id',
                'certificate_id', 'schedule_id', 'item_key', 'event_type', 'phase',
                'starts_on', 'ends_on', 'title', 'description', 'source_url',
                'schedule_version', 'google_event_id', 'html_link', 'sync_status',
                'error_code', 'error_message', 'retryable', 'created_at', 'updated_at'
            ];
            expected_types := ARRAY[
                'uuid', 'uuid', 'uuid', 'uuid', 'uuid', 'uuid', 'text', 'text', 'text',
                'date', 'date', 'text', 'text', 'text', 'timestamptz', 'text', 'text',
                'text', 'text', 'text', 'bool', 'timestamptz', 'timestamptz'
            ];
            expected_constraint_counts := ARRAY[1, 2, 7, 5];
        END IF;

        SELECT count(*) INTO column_count
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = required_table;

        SELECT EXISTS (
            SELECT 1
            FROM unnest(expected_columns, expected_types) AS expected(column_name, udt_name)
            LEFT JOIN information_schema.columns AS actual
              ON actual.table_schema = 'public'
             AND actual.table_name = required_table
             AND actual.column_name = expected.column_name
             AND actual.udt_name = expected.udt_name
            WHERE actual.column_name IS NULL
        ) INTO unexpected_column;

        IF column_count <> cardinality(expected_columns) OR unexpected_column THEN
            RAISE EXCEPTION '필수 캘린더 테이블 %의 컬럼·자료형이 예상과 다릅니다.', required_table;
        END IF;

        SELECT ARRAY[
            count(*) FILTER (WHERE contype = 'p')::integer,
            count(*) FILTER (WHERE contype = 'u')::integer,
            count(*) FILTER (WHERE contype = 'c')::integer,
            count(*) FILTER (WHERE contype = 'f')::integer
        ] INTO actual_constraint_counts
        FROM pg_constraint
        WHERE conrelid = format('public.%I', required_table)::regclass;

        IF actual_constraint_counts <> expected_constraint_counts THEN
            RAISE EXCEPTION '필수 캘린더 테이블 %의 기본키·고유키·검사·외래키 구성이 예상과 다릅니다.', required_table;
        END IF;
    END LOOP;
END
$verification$;

COMMIT;

