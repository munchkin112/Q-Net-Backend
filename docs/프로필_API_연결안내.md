# 프로필 API 연결 안내

`backend/profile_router.py`에 구현하고 `backend/main.py`에 등록했다. Google 인증 `get_current_user()`가 Bearer 토큰을 검증하며, 확인된 사용자의 UUID로 본인 데이터만 처리한다. 프론트 코드는 수정하지 않았다. 서버가 실행되면 `/docs`에 표시된다.

| API | 동작 |
|---|---|
| GET /interest-categories | 서비스 관심 분야 24개 코드·이름 |
| GET /me/profile | 본인 입력값·완료 여부·필요 항목·수정 버전 |
| PATCH /me/profile | 최초 저장 또는 전달한 항목만 수정 |

미입력은 200, profile=null, profile_completed=false, profile_version=0이다. 과거 자유 입력이 새 선택값에 맞지 않으면 추측하지 않고 missing_fields로 필요한 항목을 안내한다. 신규 저장은 필수 입력이 모두 유효해야 한다.

## 저장 준비

기존 user_profiles에 interest_category_code(관심 선택지 외래키), career_years, profile_version을 추가하는 SQL을 준비했다. **공용 DB에는 아직 적용하지 않았다.** 로그인·DB 담당자와 적용 시점을 맞춘 뒤 명시적으로 실행한다. 서버 시작 시 자동 적용하지 않는다.

```powershell
uv run python -m backend.db.add_profile_form
```

기존 recommendation_data.sql의 선택지 테이블이 먼저 필요하다. 다른 프로필 열은 유지하되, 경력 없음으로 바꾸면 이전 경력 내역을 빈 배열로 정리하고, 전공을 비우면 전공 상태를 unknown으로 정리한다. 년차로 직무명·근무 날짜를 추정하지 않는다.

## 로그인 연결 상태

`main.py`가 `get_current_user()`를 프로필 라우터에 전달한다. 인증 모델의 `id` UUID를 사용한다. 기본 프로필 조회는 `backend.profile_service.load_saved_profile_form`에 연결되어 있으며, 저장된 입력만 LLM에 전달한다. 미완성 프로필은 LLM 호출 전에 422로 거절한다. 로그인 응답의 `profile_completed`도 `get_saved_profile(user_id)`와 같은 완료 기준을 사용할 수 있지만, `/auth/me`는 아직 없다.

## 프론트 요청 계약

```json
{
  "profile_version": 0,
  "interest_category_codes": ["20"],
  "education_level": "university",
  "education_status": "graduated",
  "major": null,
  "has_career": false,
  "career_years": null
}
```

- 관심 분야 정확히 1개, 학력·졸업 상태 선택형, 전공 선택. 경력 있을 때 년차 필수다.
- 최초 저장은 버전 0, 수정은 최근 응답의 profile_version과 변경 항목만 보낸다.
- 생략은 기존 값 유지, major=null은 전공 삭제다. 경력 없음으로 변경하고 년차를 생략하면 자동으로 null로 정리한다.
- 같은 내용은 버전을 올리지 않는다. 오래된 버전은 409 PROFILE_CHANGED로 거절하므로 최신 프로필을 재조회한다.
- 프로필 수정만으로 추천을 재실행하지 않는다. 별도 POST /recommendations가 필요하다.
- 인증 사용자 ID는 본문에 보내지 않는다. 알 수 없는 필드는 422로 거절한다.

인증 오류는 공통 인증 의존성이 처리한다. 프로필 자체 오류는 현재 FastAPI `detail` 아래 `code/message/fields`이며 API 설계서의 공통 오류 래퍼와는 아직 다르다. DB 미적용·장애는 503이다.

## 검증과 남은 작업

독립 앱에서 사용자 ID·필수 입력·부분 수정·전공 삭제·버전 충돌·본문 user_id 차단을 검증한다. 실제 PostgreSQL은 공용 테이블 대신 임시 users/user_profiles/선택지 테이블을 사용하고 강제 롤백한다. HTTP 프로필 수정→재조회→추천 함수로 최신 프로필 전달도 모의 인증·모의 LLM과 실제 저장 함수를 조합해 확인한다. 실제 Google 로그인·LLM 품질 검증은 별도다.

인증 코드와 라우터 등록은 완료했다. 관심 분야 테이블·`profile_form.sql` 적용, 실제 로그인/DB 통합 시험, 공통 오류 형식 통일은 남아 있다. 추천 멱등 키와 실행 기록 저장은 별도 미완료 항목으로 유지한다. 개인 준비 계획은 로컬에만 보관한다.
