# 추천·종목별 직무 API 연결 안내

현재 구현은 `backend/recommendation_router.py`에 있고 `backend/main.py`에서 공통 `get_current_user()`로 보호해 등록했다. 프론트 코드는 수정하지 않았다. 서버가 실행되면 Swagger에 표시된다.

## 제공 API

| 메서드·경로 | 입력 | 반환 |
|---|---|---|
| POST /recommendations | Bearer 인증 + JSON `{}` | 관심 분야·저장 프로필 기준 최대 10개, LLM 적합도 순서의 카드 |
| GET /certificates/{certificate_id}/career-info | Bearer 인증 + 종목 UUID | 한 종목의 공통 추천 대상 최대 3개·연관 직무·공식 출처 |

추천 후보가 1~2개면 있는 만큼 반환하고 0개면 `status=no_results`, `items=[]`다. 실행 실패는 502/503/504로 구분한다. `position`은 반환 순서이며 객관적 점수·취업 가능성 순위가 아니다. 검색된 후보 범위 내 LLM 판단이다. 모델은 gpt-4o-mini, temperature=0, 프롬프트 버전은 2026-10-12-v4다.

추천 대상은 개인별 추천 이유와 구분한다. `recommended_for`는 승인 직무에 관심 있는 사람을 설명하는 공통 문구다. 공식 문구의 직접 인용이 아니라 Python이 구성한 설명이다. `reason`은 선택 관심 분야·사용자 프로필과 직무 근거를 연결하는 LLM 설명이다. 직무·추천 대상은 근거가 없으면 빈 배열이며, `related_jobs_status=unavailable`이다. 새 직업이나 취업 보장 표현을 생성하지 않는다.

## 로그인 담당자 연결

공통 인증 함수가 Bearer·세션 만료·폐기 여부를 확인한 뒤 반환하는 사용자 ID만 사용한다. `AuthUserResponse.id`에서 UUID를 추출하며, 요청 본문에서 사용자 ID나 프로필을 받지 않는다. 인증이 없으면 401, 인증 설정·DB를 처리할 수 없으면 503으로 차단한다. 저장 프로필 함수 `backend.profile_service.load_saved_profile_form`을 기본 연결했다. 프로필 SQL과 관심 분야·추천 자료 테이블의 DB 적용은 아직 필요하다.

프로필 함수 반환 계약:

```json
{
  "interest_category_codes": ["20"],
  "education_level": "university",
  "education_status": "graduated",
  "major": "컴퓨터공학",
  "has_career": false,
  "career_years": null
}
```

학력·졸업 상태의 허용값은 `backend/profile_form.py`와 API 설계서 최신 결정 절을 따른다. 관심 분야는 정확히 한 개, 전공은 선택, 경력 있을 때 년차 필수다. 새 `load_saved_profile_form()`은 DB 메타데이터를 제외한 입력만 반환한다. 경력 년차를 경력 날짜·직무명으로 임의 변환하지 않는다.

## 프론트 담당자 연결

- 추천 카드는 `items` 순서를 유지한다. 첫 화면은 `initial_display_count`개, 더보기는 같은 응답의 남은 항목을 표시한다. 더보기에서 LLM을 다시 호출하지 않는다.
- 카드의 `reason`은 개인별 추천 이유, `recommended_for[].text`는 종목 공통 추천 대상, `related_jobs[].name`은 근거가 있는 연관 직무다.
- 분류는 Q-Net 코드 `category`의 T/S 및 `category_name`, 설명은 `summary`를 사용한다.
- 상세 화면의 오른쪽 영역은 career-info 응답으로 연결한다. 응답 `status=unavailable`이면 공식 확인 필요 상태를 표시한다.
- 출처는 `sources[].document_id/source_url/retrieved_at/evidence_scope`로 연결한다. `source_ids`는 같은 응답의 출처 ID를 참조한다. 종목군 공통 업무·사용 제한은 `note`와 `usage_restrictions`를 함께 확인한다.

## 현재 검증과 남은 연결

실제 앱의 Swagger 라우터 등록, 인증 없을 때 차단, AuthUserResponse 사용자 UUID 연결, 저장 프로필 검증·추천 순서·개수 제한·실패/빈 결과 구분·직무 근거 소유권을 자동 시험한다. 실제 Google 로그인과 공용 DB를 이용한 통합 시험, DB 테이블 적용은 아직 하지 않았다.

기존 명세서의 추천 멱등 키 처리·추천 실행 기록 DB 저장·공통 오류 래퍼는 이 독립 라우터에서 아직 연결하지 않았다. 현재 오류는 FastAPI `detail` 아래 `code/message`다. 실제 배포 API로 연결할 때 공통 계약과 맞춰야 한다. 과거 ‘순위 없는 목록’ 정책은 이번 사용자 결정에 따라 적합도 순서로 바뀌었다.
