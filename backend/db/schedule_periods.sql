-- 실제로 접수가 열리는 복수 기간과 기술사 면접 단계를 추가한다.
ALTER TABLE schedules ADD COLUMN IF NOT EXISTS registration_periods jsonb
    NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(registration_periods) = 'array');

ALTER TABLE schedules DROP CONSTRAINT IF EXISTS schedules_phase_check;
ALTER TABLE schedules ADD CONSTRAINT schedules_phase_check
    CHECK (phase IN ('written', 'practical', 'interview', 'first', 'second', 'other'));

-- 기존에 확인한 단일 접수기간은 그대로 옮기고 미확인 날짜는 채우지 않는다.
UPDATE schedules SET registration_periods = jsonb_build_array(
    jsonb_build_object('starts_on', registration_start, 'ends_on', registration_end)
)
WHERE registration_periods = '[]'::jsonb AND registration_start IS NOT NULL AND registration_end IS NOT NULL;
