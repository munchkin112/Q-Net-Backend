-- 전문자격 원문·수집 결과를 보관한다. 조회용 상세정보나 응시조건 비교와 구분한다.
CREATE TABLE IF NOT EXISTS sources (
    source_key text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    certificate_id uuid REFERENCES certificates(id) ON DELETE RESTRICT,
    series_code text,
    kind text NOT NULL CHECK (kind IN ('details', 'schedules')),
    collection_status text NOT NULL CHECK (collection_status IN ('fetched', 'empty', 'failed')),
    source_url text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_sha256 text NOT NULL,
    stored_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_key, retrieved_at)
);
