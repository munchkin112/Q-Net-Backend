-- 종목별 시험 상세정보를 보관한다. 응시조건 비교는 포함하지 않는다.
CREATE TABLE exam_information (
    certificate_id uuid PRIMARY KEY REFERENCES certificates(id) ON DELETE RESTRICT,
    subjects jsonb NOT NULL CHECK (jsonb_typeof(subjects) = 'object'),
    pass_criteria jsonb NOT NULL CHECK (jsonb_typeof(pass_criteria) = 'object'),
    fees jsonb NOT NULL CHECK (jsonb_typeof(fees) = 'object'),
    raw_acquisition_text text,
    raw_fee_text text,
    retrieved_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
