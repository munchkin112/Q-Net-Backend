-- Initial confirmed scope. No eligibility, Calendar or roadmap tables.
-- Run once using: python -m backend.db.initialize
CREATE TABLE users (
    id uuid PRIMARY KEY,
    provider text NOT NULL CHECK (provider = 'google'),
    provider_subject_id text NOT NULL CHECK (btrim(provider_subject_id) <> ''),
    email text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_subject_id)
);

CREATE TABLE user_profiles (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    education_level text,
    education_status text CHECK (education_status IN ('graduated', 'enrolled', 'expected', 'other')),
    graduation_date date,
    major text,
    major_status text CHECK (major_status IN ('provided', 'not_applicable', 'unknown')),
    has_career boolean,
    career_history jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(career_history) = 'array'),
    qualifications jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(qualifications) = 'array'),
    desired_job text,
    current_status text,
    location text,
    target_date date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE certificates (
    id uuid PRIMARY KEY,
    qnet_code text NOT NULL UNIQUE CHECK (btrim(qnet_code) <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    category text NOT NULL CHECK (btrim(category) <> ''),
    career_tags jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(career_tags) = 'array'),
    description text,
    source_url text NOT NULL,
    last_synced_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE schedules (
    id uuid PRIMARY KEY,
    certificate_id uuid NOT NULL REFERENCES certificates(id) ON DELETE RESTRICT,
    year smallint NOT NULL CHECK (year BETWEEN 1900 AND 9999),
    round_key text NOT NULL CHECK (btrim(round_key) <> ''),
    round_label text NOT NULL CHECK (btrim(round_label) <> ''),
    phase text NOT NULL CHECK (phase IN ('written', 'practical', 'interview', 'first', 'second', 'other')),
    registration_start date,
    registration_end date,
    registration_periods jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(registration_periods) = 'array'),
    exam_start date,
    exam_end date,
    result_date date,
    result_display_end date,
    vacancy_registration_start date,
    vacancy_registration_end date,
    exam_site text,
    source_url text NOT NULL,
    last_synced_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (certificate_id, round_key, phase),
    CHECK (registration_start <= registration_end),
    CHECK (COALESCE(registration_end, registration_start) <= COALESCE(exam_start, exam_end)),
    CHECK (exam_start <= exam_end),
    CHECK (COALESCE(exam_end, exam_start) <= result_date),
    CHECK (result_date <= result_display_end),
    CHECK (vacancy_registration_start <= vacancy_registration_end),
    CHECK (COALESCE(vacancy_registration_end, vacancy_registration_start) <= COALESCE(exam_start, exam_end))
);
CREATE INDEX schedules_certificate_year_idx ON schedules(certificate_id, year);
