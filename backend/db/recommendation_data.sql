-- 서비스 관심 선택지다. 공식 NCS 분류나 자격증별 고정 분류표가 아니다.
CREATE TABLE IF NOT EXISTS recommendation_interest_categories (
    code text PRIMARY KEY CHECK (code ~ '^(0[1-9]|1[0-9]|2[0-4])$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 요약·직업별 근거·원문을 함께 보관한다. 기존 종목·시험정보·sources는 갱신하지 않는다.
CREATE TABLE IF NOT EXISTS certificate_recommendation_contexts (
    certificate_id uuid PRIMARY KEY REFERENCES certificates(id) ON DELETE RESTRICT,
    qnet_code text NOT NULL UNIQUE REFERENCES certificates(qnet_code) ON DELETE RESTRICT,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (payload ->> 'review_status' IN (
        'assistant_reviewed_summary_only', 'assistant_reviewed_summary_and_roles')),
    CHECK (length(btrim(payload ->> 'summary')) > 0),
    CHECK (jsonb_typeof(payload -> 'related_jobs') = 'array'),
    CHECK (jsonb_typeof(payload -> 'evidence_documents') = 'array')
);
COMMENT ON TABLE certificate_recommendation_contexts IS
    '승인 직무 요약과 공식 근거. 응시자격 판정·최신 법적 권한·개인별 추천 결과가 아님';
