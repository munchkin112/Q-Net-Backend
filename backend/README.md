# 확정된 DB 작업

[전체 작업 현황과 다음 순서](../docs/프로젝트_진행현황.md), [API 설계](../docs/API_설계_초안.md), [DB 설계](../docs/DB_설계_초안.md)를 함께 확인한다.

Render PostgreSQL 연결과 테이블 적용을 완료했다. 공식 종목 613개, 상세정보 510종목을 저장했다. 시험일정은 기술자격 513개 전체의 공식 페이지를 조사해 475종목·1,922단계까지 확대했다. 상세정보는 464개가 세 정보 확보, 46개가 일부 미확인, 3개가 세 정보 모두 미확보다. 로그인·프로필 저장 HTTP API·Agent는 아직 연결하지 않았다.

이번 확대에서 필기·실기, 필기·면접, 실기 단독을 구분했다. 단계 표시가 없는 공식 과목·기준은 common에 보관하고 미확인은 null로 남긴다. [종목별 확대 결과](../docs/기술자격_상세정보_확대결과.md)에 모든 미확인 종목과 사유를 기록했다. 저장된 510종목 전체 구조 검증과 대표 16종목의 실제 HTTP 응답 검증을 통과했다.

상세정보 연동의 실행 순서, 핵심 함수, 입력·출력과 오류 처리는 [시험 상세정보 설명](../docs/시험_상세정보_연동.md)에 정리했다.

여러 기술자격을 순서대로 수집하는 `backend.sync_batch`를 추가했다. 기본 표본은 기사 5개·산업기사 2개·기능사 3개다. 상세정보와 일정의 성공·실패를 따로 기록하고 실패 후에도 다음 작업을 계속한다. 미리보기는 `python -m backend.sync_batch`, 저장은 `--apply`, 종목 선택은 `--codes`, 작업 선택은 `--only details` 또는 `--only schedules`로 한다. [일괄 수집 설명](../docs/기술자격_일괄수집.md)에서 실행 방법과 결과 상태를 확인할 수 있다.

일정 확대 전에는 API 표본 10종목 중 5개 성공, 5개 시간초과·제공기관 오류였다. 산업안전기사의 공식 페이지 일정까지 포함한 기존 6종목·36단계에서 이번 전체 확대를 시작했다. 공식 페이지 수집·원본 재처리 명령을 추가하고 기존 변환·검증·저장 함수를 재사용했다. 기술사 면접, 여러 접수기간, 빈자리 접수를 지원한다. 정기 일정이 빈 21종목과 종목명을 확인하지 못한 17종목은 임의로 날짜를 저장하지 않는다. [시험일정 확대 결과](../docs/시험일정_연동_확대결과.md)에 모든 예외와 조회 방법을 정리했다.

일정 원본은 `research/all_technical_schedule_sources.json`과 `_html` 폴더, 저장 결과는 `research/all_technical_schedule_applied.json`, 전체 DB·HTTP 검증은 `research/all_technical_schedule_verification.json`이다. 일부 기존 행은 원문에 없는 확인 값을 보존하고 접수기간만 자체 출처로 보완한다. 상세정보 결과는 `research/all_technical_detail_applied.json`과 `research/all_technical_detail_verification.json`에 따로 기록했다.

## API 문서 실행

프로젝트 루트에서 `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`을 실행하고 http://127.0.0.1:8000/docs 를 연다. 서버 상태는 DB 없이 확인할 수 있고, 실제 일정 조회는 DATABASE_URL과 초기 테이블 적용이 필요하다. Schemas에는 프로필 입력 구조도 표시되지만 프로필 저장 API는 로그인 구현 전이라 제공하지 않는다.

| 상태 | 내용 |
| --- | --- |
| 구현 | users, user_profiles, certificates, schedules 테이블 SQL |
| 구현 | 프로필 부분 저장/조회, 날짜·상태 검증 |
| 구현 | 보유 자격·경력 날짜 선택 입력 |
| 구현 | 회차 아래 필기/실기/면접별 행 저장 및 실제 접수기간 검증 |
| 구현 | 공식 XML 호출·최대 1회 재시도·종목/일정 변환 |
| 구현 | 공식 코드 기반 종목 저장·갱신과 종목명·코드 검색 API |
| 검증 완료 | 기존 응답과 실시간 공식 응답의 종목 613개·정보처리기사 6단계 변환 |
| 적용·검증 완료 | Render 기본 테이블 4개와 시험정보 테이블, 종목 613개 저장 |
| 적용·검증 완료 | 기술자격 일정 475종목·1,922단계, 복수 접수기간·빈자리 접수와 기존 ID 보존 |
| 적용·검증 완료 | 기술자격 전체 상세정보 조사, 510종목 저장, 전체 구조와 대표 16종목 HTTP 검증 |
| 준비/비활성 | 북마크 생성·조회·삭제 코드와 테이블 SQL 전체 주석 |
| 보류 | 응시조건 저장·비교, Calendar, Agent 상태 저장 |
| 제외 | 로드맵 테이블·API·학습시간 필드 |

## 파일과 사용 흐름

- `db/schema.sql`: 초기 테이블 4개. 종목과 사용자는 프로필/일정의 FK 대상이므로 포함했다.
- `db/connection.py`: 환경변수 DATABASE_URL로 연결하고 성공 시 commit, 오류 시 rollback, 마지막에 연결 종료.
- `db/initialize.py`: 명시적으로 실행할 때만 초기 SQL 적용. 앱 시작 시 자동 적용하지 않는다.
- `db/exam_information.sql`: 시험과목·합격기준·응시료와 각 정보의 출처·조회 시각. 신규 DB 초기화에 함께 적용한다.
- `db/add_exam_information.py`: 이미 기본 테이블이 있는 DB에 상세정보 테이블만 추가한다.
- `exam_data.py`, `exam_schemas.py`, `db/exam_repository.py`: 공식 상세정보 원문 변환·입력 검증·저장과 조회.
- `sync_exam_information.py`: 공식 상세정보 재조회와 미리보기, --apply로 명시적 DB 저장.
- `schemas.py`: ProfilePatch와 ScheduleInput의 입력 검증.
- `official_schedule_page.py`: 공식 일정 표를 읽고 기존 회차 변환 함수를 재사용.
- `sync_schedule_pages.py`: 기술자격 전체 일정 페이지의 원본·조회 시각 수집.
- `apply_schedule_pages.py`: 보관한 원본 검증과 종목별 일괄 저장. 기본은 미리보기.
- `db/schedule_periods.sql`, `db/add_schedule_periods.py`: 기존 일정의 접수기간 목록·면접 단계 추가.
- `db/repository.py`: get_profile / save_profile / save_schedule / list_schedules.
- `db/bookmarks.sql`: 나중에 주석을 해제하여 적용할 북마크 SQL.

프로필 저장 흐름: 서버에서 확인한 사용자 ID → ProfilePatch → 기존 행 잠금 및 병합 → 상태 모순 검사 → 전달한 필드만 저장 → 저장된 행 반환. 값 생략은 유지, 일반 필드 null은 삭제, 배열 null은 []로 비운다. 경력·자격 취득 날짜가 없어도 저장 가능하며 필요할 때 추가한다. 사용자 추정 경력연수는 별도 저장/확정 계산하지 않는다.

일정 저장 흐름: 공식 자료를 한 단계씩 정규화 → ScheduleInput 날짜 검증 → 종목+회차키+단계 기준 upsert → 저장된 행 반환. 필기와 실기·면접은 다른 ID를 가진다. 기존 키를 다시 저장하면 ID를 유지한다. `registration_periods`의 실제 접수기간을 사용하며 시작·종료 필드는 전체 범위다. 각 기간에는 출처와 조회 시각을 보관한다. API 기반 명령도 더 상세한 기존 기간을 지울 입력은 보존한다. 공식 페이지 일괄 저장은 같은 종목의 모든 단계를 한 트랜잭션으로 처리한다. 주기적인 자동 동기화는 아직 설정하지 않았다.

source_url과 last_synced_at을 종목/일정에 직접 보관한다. 필드별 출처 연결 테이블과 응시조건 JSONB는 합의 전이라 이번에 만들지 않았다. qnet_code는 숫자가 아닌 문자열이다. 같은 회차 숫자라도 시행계획/대상 조건이 다르면 round_key를 구분해야 한다.

상세정보에는 subjects, pass_criteria, fees 각각의 JSON에 실제 값·확인 상태·source_url·retrieved_at을 직접 보관한다. 응시조건 비교와 분리된 시험정보 구현이며 별도의 sources 테이블은 추가하지 않았다. 시험정보가 없는 종목은 상세 API에서 null과 확인 필요 상태를 반환한다.

## Render 연결과 초기 적용

Render 내부의 같은 지역 서비스는 Internal Database URL, 로컬 개발은 External Database URL을 사용한다. 로컬 외부 연결에는 `sslmode=require` 이상을 사용한다. 연결 URL은 공개 저장소/문서/로그에 넣지 않고 환경변수로 설정한다. [Render 공식 연결 문서](https://render.com/docs/postgresql-creating-connecting)

프로젝트 루트에서:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
# DATABASE_URL은 실행 환경의 비밀 환경변수에 설정한다.
.\.venv\Scripts\python.exe -m backend.db.initialize
```

`backend/.env`의 DATABASE_URL에 연결 URL을 입력하면 API 서버와 실행 명령이 자동으로 읽는다. 실행 환경에 이미 설정된 값이 있으면 환경변수를 우선한다. 설정을 변경한 뒤 API 서버를 재시작한다. 이 파일은 Git에서 제외된다. 실제 DATABASE_URL이 있어야 연결 가능하다. initialize는 새 DB에서 한 번만 실행한다. 재실행하면 기존 테이블 오류로 전체 트랜잭션을 롤백한다. 기존 데이터베이스 변경은 별도 마이그레이션이 필요하다.

실제 접속 검사는 `python -m backend.db.check` 또는 GET /health/database로 실행한다. 설정 유무·접속 성공·필수 테이블 존재를 구분하고 URL/비밀번호를 반환하지 않는다. tables_ready는 테이블 존재 확인이며 모든 컬럼의 호환성·저장 성공까지 보장하지 않는다. DB 미설정/접속 실패/초기 테이블 부재 시 HTTP 503을 반환한다.

Render 생성 후 순서: 연결 URL 입력 → DB 접속 검사 → 초기 테이블 생성 → 검사 재실행 → `backend.sync_official --live --apply`로 데이터 저장 → 검색·일정 API 조회. 2026-10-05 실제 연결·초기 적용·공식 자료 저장·조회 검증을 완료했다. 종목은 기술자격 513개와 전문자격 100개이며, 이후 표본 연동으로 일정 6종목·36단계까지 저장했다. 최초 동기화 결과는 `research/normalized_render_sync.json`, 최초 DB·API 확인 결과는 `research/render_verification.json`에 기록했다.

저장 함수는 connection을 받아 실행한다. database_connection() 범위가 최종 commit/rollback을 관리한다. Google 로그인으로 users를 등록하는 코드는 아직 없으므로 프로필 저장 전 users 행이 필요하고, 일정 저장 전 certificates 행이 필요하다. FK 오류는 호출자에게 전달되며 보류한 기능으로 우회하지 않는다.

## 북마크 활성화

1. `db/bookmarks.sql`에서 SQL 부분의 `-- `를 제거하고 기존 DB에 적용한다.
2. `db/repository.py`의 FUTURE BOOKMARK 아래 함수 3개에서 `# `를 제거한다.
3. 주석을 해제한 add_bookmark / get_bookmarks / delete_bookmark를 사용할 수 있다. HTTP API 연결은 API 구현 단계에서 한다.

북마크는 자격증별 저장이며 필기/실기 선택과 독립적이다. 사용자+종목 고유키로 중복을 방지한다. 주석을 해제하는 것만으로 이미 실행 중인 DB에 테이블이 생기는 것은 아니므로 SQL 적용이 필요하다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

기본 테스트는 부분 입력, 경력 모순, 날짜 역전, 시간대 없는 조회 시각 등을 확인한다. 별도의 테스트 PostgreSQL을 마련하고 TEST_DATABASE_URL을 설정하면 DB 통합 테스트도 수행한다. 통합 테스트는 임시 스키마 안에서 실제 SQL/저장 함수를 실행하고 마지막에 rollback한다. 실제 운영 URL 대신 전용 테스트 DB를 사용한다.

SQL 문법 검사는 개발 도구 pglast로 별도 수행했다. 2026-10-05 Render에서 임시 스키마를 만들어 기존 DB 통합 테스트를 실행했다. 프로필 부분 저장·모순 처리, 종목 검색·코드 앞자리 0 유지, 필기/실기 분리, 중복 저장 시 ID 유지, 오래된 일정의 덮어쓰기 방지를 통과했고 마지막에 전체 롤백했다. 임시 스키마와 검증용 사용자·프로필이 남지 않은 것도 확인했다. 실제 검색·일정·DB 상태·Swagger 응답은 HTTP 200이었다. 연결 URL은 문서·검증 파일에 기록하지 않았으며 Google 권한과 팀원 초대는 아직 설정하지 않았다.

## 이번 작업의 실행 순서

[공유한 수업 저장소](https://github.com/yleessam/2026-aio2-guide)의 관련 FastAPI·Pydantic·httpx·CRUD와 직접 PostgreSQL 연결 예제를 확인했다. 일반 함수·조건문·반복문을 중심으로 구현하고 필수 SQL/XML 처리에는 한국어 설명을 붙였다.

```text
공식 API 호출 또는 기존 조사 응답 읽기
→ XML item을 딕셔너리로 변환
→ 공식 목록과 선택 종목 확인
→ 회차를 필기·실기 두 행으로 변환
→ 필수 값·종목 일치·날짜 순서 검증
→ 미리보기 저장
→ --apply를 지정한 경우에만 DB 저장
```

| 파일/함수 | 역할 |
| --- | --- |
| official_api.py / request_items | httpx 호출, HTTP와 공식 오류코드 확인, 최대 1회 재시도 |
| official_data.py / normalize_technical_schedules | 회차를 필기·실기 행으로 나누고 발표일/조회 종료일 구분 |
| sync_official.py / prepare_official_data | 공식 목록과 종목을 대조하고 저장 전에 전체 입력 검증 |
| sync_official.py / apply_official_data | 검증된 목록·일정을 한 트랜잭션으로 저장 |
| db/repository.py / save_certificate | 공식 코드로 갱신하되 기존 ID와 팀 태그 유지 |
| services.py / list_certificates | DB 연결을 관리하고 종목명·코드 검색 |

프로젝트 루트에서 실행:

```powershell
# 기존 공식 응답으로 검증: DB와 네트워크 연결 불필요
.\.venv\Scripts\python.exe -m backend.sync_official

# 공식 API에서 새로 조회·검증: DB 저장은 하지 않음
.\.venv\Scripts\python.exe -m backend.sync_official --live --output research/normalized_live_preview.json

# DB를 연결하고 초기 SQL을 적용한 뒤에만 실행
.\.venv\Scripts\python.exe -m backend.sync_official --live --apply
```

입력: 기본 qnet_code=1320(정보처리기사), 공식 종목 목록과 getJMList XML. 출력: 검증된 종목 목록과 단계별 일정 미리보기 JSON. 스냅샷은 원래 조회 시각을 유지하며 현재 재조회로 표시하지 않는다. DB 미리보기용 임시 UUID는 실제 DB 저장 시 조회한 종목 ID로 교체한다.

현재 저장된 일정 스냅샷은 정보처리기사만 지원한다. 실시간 조회는 --qnet-code로 다른 기술자격을 지정할 수 있지만 종목별 성공을 보장하지 않는다. 전문자격·상시시험은 별도 연동이 필요하다. 이번 키 없는 성공이 앞으로의 인증 정책을 보장하지 않으며 인증키가 필요한 통합 API는 아직 연결하지 않았다.

오류 지점: 인증 정책 변경·통신 실패·타임아웃, 잘못된 XML/날짜, 종목명 불일치, 시행계획명의 연도 누락, DB 연결/테이블 미설정. 정상 빈 목록은 재시도하지 않고, 오류가 난 자료를 만들어 저장하지 않는다. DB 저장 중 실패하면 트랜잭션을 취소한다.

검색 API: GET /certificates?q=정보처리&category=T&limit=20&offset=0. 현재 페이지 방식은 limit+offset이며 Render DB 연결과 목록 저장 이후 실행 가능하다. 검색 결과는 현재 시행 여부나 응시 가능성을 확정하지 않는다.

추가 학습 개념: XML 파싱, SQL ON CONFLICT(같은 키면 갱신), 트랜잭션(모두 성공할 때만 저장), 사용자 정의 예외(오류 종류 전달). 실제 저장·오류 처리를 위해 필요한 부분이다.
