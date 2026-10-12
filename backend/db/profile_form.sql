-- 명시적으로 적용할 때만 기존 프로필에 화면 입력 필드를 추가한다.
-- recommendation_data.sql의 관심 선택지 테이블이 먼저 필요하다.
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS interest_category_code text
        REFERENCES recommendation_interest_categories(code),
    ADD COLUMN IF NOT EXISTS career_years numeric CHECK (career_years >= 0 AND career_years <= 80),
    ADD COLUMN IF NOT EXISTS profile_version integer NOT NULL DEFAULT 0 CHECK (profile_version >= 0);

-- 과거 학력 자유 입력과 경력 날짜는 추측해서 변환하지 않는다.
-- 새 API에서 기존 필수 입력을 검증한 뒤 저장하며 다른 프로필 열은 유지한다.
