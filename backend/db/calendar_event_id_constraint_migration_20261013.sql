-- PostgreSQL에서 큰 반복 범위 {5,1024}가 실행 오류를 일으켜 등록을 막는 문제를 고친다.
-- 허용 문자와 길이를 별도로 검사한다. 기존 이벤트와 고유키는 유지한다.
-- 새 검사로 기존 값을 확인한 뒤 문제 정규식 검사만 제거한다.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '15s';
DO $migration$
DECLARE
    old_constraint record;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.calendar_events'::regclass
          AND conname = 'calendar_events_google_event_id_format_check'
    ) THEN
        ALTER TABLE public.calendar_events
        ADD CONSTRAINT calendar_events_google_event_id_format_check
        CHECK (length(google_event_id) BETWEEN 5 AND 1024 AND google_event_id ~ '^[a-v0-9]+$');
    END IF;
    FOR old_constraint IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'public.calendar_events'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%google_event_id%'
          AND pg_get_constraintdef(oid) LIKE '%{5,1024}%'
    LOOP
        EXECUTE format('ALTER TABLE public.calendar_events DROP CONSTRAINT %I', old_constraint.conname);
    END LOOP;
END
$migration$;
COMMIT;
