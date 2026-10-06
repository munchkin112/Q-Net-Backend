# 기술자격 일괄 수집

## 실제 실행 결과 — 2026-10-05

10개 종목의 상세정보를 모두 저장했고 상세 조회 API에서 HTTP 200과 과목·기준·응시료를 확인했다. 일정 API는 5개 종목에서 저장 성공, 5개 종목에서 실패했다. 산업안전기사의 이전 공식 페이지 일정 6단계는 유지되어 현재 DB에는 일정이 있는 종목 6개·총 36단계가 있다. 전체 종목 목록은 613개이며 상세정보는 10개다.

| 종목 | 상세정보 | 이번 일정 수집 | 현재 저장 일정 |
| --- | --- | --- | --- |
| 정보처리기사 | 저장·조회 정상 | 성공 | 6단계 |
| 산업안전기사 | 저장·조회 정상 | 시간초과 | 기존 공식 페이지 6단계 유지 |
| 전기기사 | 저장·조회 정상 | 성공 | 6단계 |
| 건축기사 | 저장·조회 정상 | 1회 재시도 후 성공 | 6단계 |
| 토목기사 | 저장·조회 정상 | 제공기관 오류, 1회 재시도 실패 | 미수집 |
| 정보처리산업기사 | 저장·조회 정상 | 성공 | 6단계 |
| 전기산업기사 | 저장·조회 정상 | 1회 재시도 후 성공 | 6단계 |
| 한식조리기능사 | 저장·조회 정상 | 시간초과 | 미수집 |
| 전기기능사 | 저장·조회 정상 | 시간초과 | 미수집 |
| 정보기기운용기능사 | 저장·조회 정상 | 시간초과 | 미수집 |

실패한 일정 작업도 기존 API의 최대 1회 재시도까지 실행했다. 해당 5건의 실패 때문에 명령 종료 코드는 1이며, 수집 루프는 10개 모두 처리하고 `completed=true`로 끝났다. 일정 API의 정상 HTTP 응답과 빈 목록은 제공 데이터의 부재를 구분하기 위한 별도 상태로 준비했지만 이번 실행에서는 빈 정상 목록 없이 위 오류가 발생했다.

기존 일정을 지우지 않은 것과 종목·회차·단계 고유키 중복 0건을 확인했다. 전체 자동 검증은 64개 중 62개 통과·전용 DB 통합 테스트 2개 건너뛰기였고, 실제 Render 저장 자료는 별도로 10개 종목 모두 HTTP 조회해 검증했다.

실행 결과: `research/batch_sync_result.json`. 실제 DB·API 검증: `research/batch_sync_verification.json`. 저장 전 공식 원문 표본: `research/batch_detail_preview.json`.

## 작업 흐름

공식 목록에 저장된 종목 코드를 받아 여러 기술자격의 상세정보·일정을 순서대로 수집한다. 새 테이블이나 종목별 클래스를 추가하지 않고 기존 호출·변환·검증·저장 함수를 재사용한다.

```text
종목 코드 목록 입력 → 중복 코드 제외
→ DB에서 종목명·기술자격 여부 확인
→ 상세정보·수수료 조회와 검증 → 성공한 경우 상세정보 저장
→ 시험일정 조회와 날짜 검증 → 성공한 경우 일정 저장
→ 해당 종목의 결과 파일 기록
→ 요청 간격을 두고 다음 종목 처리
→ 성공·실패·누락·빈 일정 개수 집계
```

상세정보와 일정은 독립된 작업이다. 상세정보가 실패해도 일정은 실행하며 한 종목이 실패해도 다음 종목을 계속한다. 상세정보 저장과 종목별 전체 일정 저장은 각각 하나의 트랜잭션이므로 해당 작업의 중간 실패는 취소한다. 이미 성공한 다른 종목이나 상세정보 작업은 유지한다.

## 기본 표본 10개

| 종목 | 공식 코드 |
| --- | --- |
| 정보처리기사 | 1320 |
| 산업안전기사 | 1431 |
| 전기기사 | 1150 |
| 건축기사 | 1630 |
| 토목기사 | 1250 |
| 정보처리산업기사 | 2290 |
| 전기산업기사 | 2140 |
| 한식조리기능사 | 7910 |
| 전기기능사 | 7780 |
| 정보기기운용기능사 | 6892 |

코드는 DB의 공식 목록에서 대조했다. 전문자격은 현재 일괄 수집 대상에서 거절한다. 기본 표본을 넘어서는 기술자격은 코드로 지정할 수 있으나 원문 형식과 일정 반환 여부는 별도 검증이 필요하다.

## 실행 방법

프로젝트 루트에서 실행한다. 명령은 `backend/.env`의 DATABASE_URL을 읽으며 기본 동작은 검증과 결과 기록이다. DB 저장은 `--apply`로 선택한다.

```powershell
# 10개 표본의 상세정보와 일정 조회·검증, DB 저장 없음
.\.venv\Scripts\python.exe -m backend.sync_batch

# 검증에 성공한 작업을 Render DB에 저장
.\.venv\Scripts\python.exe -m backend.sync_batch --apply

# 지정한 여러 종목의 상세정보만 저장
.\.venv\Scripts\python.exe -m backend.sync_batch --codes 1150 1630 1250 --only details --apply

# 일정만 다시 조회하고 결과 파일을 별도로 기록
.\.venv\Scripts\python.exe -m backend.sync_batch --codes 1320 1431 --only schedules --apply --output research/schedule_retry_result.json
```

`--interval`은 기본 1초이며 외부 작업 사이와 종목 사이에 대기한다. 기존 API 함수의 요청별 제한 시간 20초·최대 1회 재시도를 재사용한다. 시간초과가 있는 종목은 더 오래 걸릴 수 있다. 전체 513개를 동시에 호출하지 않으며 주기적 자동 실행은 설정하지 않았다.

## 결과 확인

### 기술자격 시험일정 전체 확대

일정 API의 시간초과·제공기관 오류가 반복되어 종목별 공식 페이지의 일정 표를 수집하는 실행 명령을 추가했다. 기존 날짜 변환·ScheduleInput·저장 함수를 재사용한다. HTML은 실행하지 않고 표의 본문만 읽는다. 공식 표는 셀 닫는 태그가 생략될 수 있어 이를 처리하며, 일반인 응시 불가로 명시된 학교별 검정은 제외한다. 빈 일정은 기존 DB를 삭제하지 않는다.

```powershell
# 기존 DB에 실제 접수기간 목록과 기술사 면접 단계 추가. 이미 이번 작업에서 적용함.
.\.venv\Scripts\python.exe -m backend.db.add_schedule_periods

# 기술자격 전체의 공식 일정 원본 수집. DB 저장 없음.
.\.venv\Scripts\python.exe -m backend.sync_schedule_pages --interval 0.5

# 확보한 원본과 검토한 2026년 시행공고의 접수 예외를 검증.
.\.venv\Scripts\python.exe -m backend.apply_schedule_pages

# 검증한 자료만 종목별 트랜잭션으로 DB에 저장.
.\.venv\Scripts\python.exe -m backend.apply_schedule_pages --apply --output research/all_technical_schedule_applied.json

# 전체 DB와 로컬 8000 API의 대표 종목 확인.
.\.venv\Scripts\python.exe -m research.verify_schedule_expansion
```

원본은 `research/all_technical_schedule_sources.json`과 같은 이름의 `_html` 폴더에 보관한다. `--from-report`, `--output`으로 다른 결과 파일을 지정할 수 있다. 원본의 조회 시각을 유지하고 실패한 종목 이후에도 계속한다. 기본 미리보기에는 DB 쓰기가 없다. 일부 종목의 검증 실패를 기록한 경우 종료 코드 1을 반환해도 다른 종목은 처리된다.

`--notice`는 사람이 원문을 검토해 옮긴 공식 시행공고의 접수 예외다. 기본 파일은 `research/technical_2026_annual_notice.json`이며 PDF 원본도 보관했다. 기사 3회 실기 접수의 9/21~9/23와 9/28을 분리하고 각 기간에 공고의 출처·실제 조회 시각을 남긴다. 연도가 바뀌면 새 공고를 확인해야 한다. 기술사 면접의 두 접수기간은 종목 페이지에서 직접 읽는다. 날짜 범위가 공고와 다르면 임의로 맞추지 않고 실패로 기록한다.

공식 페이지에 없는 기존 결과조회 종료일 등의 날짜는 지우지 않는다. 이런 행은 원래 전체 자료를 유지하고 접수 범위가 일치할 때만 `registration_periods`를 자체 출처와 함께 보완한다. 따라서 일정의 `source_url/last_synced_at`과 접수기간의 출처·시각이 다를 수 있다. `retained_rows`는 전체 자료를 유지한 행 수다. 오래된 원본은 더 최근에 확인한 기간을 덮어쓰지 않는다. API 기반 기존 실행 명령도 이미 확인한 기간을 지울 입력은 보존한다.

상시검정의 지역·시험장별 일정과 개인 배정 날짜는 이번 수집 범위에 포함하지 않는다. 공통 연간표의 날짜를 모든 종목에 복제하지 않는다. 정기 일정이 빈 종목과 종목명을 확인하지 못한 페이지는 결과 문서에서 구분한다.

전체 확대는 먼저 원본을 확보하고, 원문 형식 보완 후 외부 재호출 없이 다시 검증·저장하는 두 단계로 진행한다.

```powershell
# 기술자격 전체의 상세정보 원본 확보. DB 저장 없음.
.\.venv\Scripts\python.exe -m backend.sync_batch --all-technical --only details --interval 0.5 --output research/all_technical_detail_sources.json

# 중단됐으면 같은 파일을 사용해 완료한 종목 다음부터 이어서 실행.
.\.venv\Scripts\python.exe -m backend.sync_batch --all-technical --only details --interval 0.5 --resume --output research/all_technical_detail_sources.json

# 원본 재처리와 부분 정보 저장. 실제 원본 조회 시각 유지.
.\.venv\Scripts\python.exe -m backend.sync_batch --from-report research/all_technical_detail_sources.json --allow-partial --apply --output research/all_technical_detail_applied.json

# 실행 중인 로컬 8000 서버와 DB 전체 정보 검증.
.\.venv\Scripts\python.exe -m research.verify_detail_expansion
```

`--allow-partial`은 원본 재처리에서 사용한다. 한 API만 성공했어도 확보한 정보를 저장할 수 있으며, 실패한 API의 출처·조회 시각을 만들어 넣지 않는다. `collection_error`에 원래 호출 실패를 남긴다. `validated_partial`은 일부 정보 검증, `saved_partial`은 일부 정보 저장이며 세 정보가 모두 확인된 성공과 구분한다. 모든 정보가 미확인인 종목은 저장하지 않는다. 이미 확인된 값을 지울 입력은 기존 전체 자료를 유지한다.

기본 결과 파일은 `research/batch_sync_result.json`이다. 종목마다 완료 즉시 임시 파일을 쓴 뒤 결과 파일로 교체한다. 중단 시 앞선 종목 결과를 확인할 수 있다. 같은 코드를 재실행해도 기존 종목·일정 ID는 유지하고, 조회 시각이 더 오래된 자료는 기존 값을 덮어쓰지 않는다.

| 상태 | 의미 |
| --- | --- |
| validated | 필요한 값과 출처 검증 완료, 미리보기 모드라 저장하지 않음 |
| saved | 검증한 자료를 DB에 저장함 |
| unchanged | 더 최신 자료가 이미 있어 전체 또는 일부 기존 자료를 유지함 |
| incomplete | 저장 조건을 충족하지 못함. --allow-partial에서도 확인한 값이 전혀 없으면 저장하지 않음 |
| empty | 정상 일정 응답이지만 반환된 일정 없음. 기존 일정 유지 |
| failed | 호출·변환·DB 저장 중 오류. error_type, step, retry_count 확인 |
| not_requested | --only 옵션으로 제외한 작업 |

상세정보에는 변환 결과와 공식 응답 item을 함께 기록해 형식 문제를 다시 확인할 수 있다. DB URL과 비밀번호는 결과에 기록하지 않는다. 전체 완료 여부는 `completed`, 작업별 집계는 `summary`에 있다. 일부 failed/incomplete가 있으면 전체 처리는 마치되 종료 코드는 1로 반환한다. 오류가 있는 실행을 전부 성공한 것으로 표시하지 않는다.

일정이 empty라고 자격시험 자체가 없다는 뜻은 아니다. 특히 상시시험은 이 정기시험 API와 별도 확인이 필요하다. 시간초과·빈 일정이 발생하면 기존 DB 자료와 종목별 공식 페이지를 참고한다. 일괄 명령에서 공식 페이지로 자동 전환하는 기능은 아직 제공하지 않는다.

## 이번에 보완한 공통 코드

- `backend/exam_data.py / subject_list`: 공백 없이 붙은 연속 과목 번호도 분리한다. 토목기사 6과목과 정보처리산업기사 3과목으로 확인했다.
- `backend/exam_data.py / find_section`: 합격기준 다음의 작업형 시험 안내·안전등급은 합격기준에 넣지 않는다.
- `backend/sync_batch.py / collect_details`: 기존 상세정보 호출·변환·저장 함수 재사용.
- `backend/sync_batch.py / collect_schedules`: 기존 일정 호출·날짜 검증·저장 함수 재사용.
- `backend/sync_batch.py / run_batch`: 순차 실행과 종목별 결과 기록·실패 후 계속 처리.

검증에는 실제 10종목 응답, 중복 코드, 없는 코드, 상세정보 실패 뒤 일정 계속 처리, 빈 일정의 기존 데이터 보존, DB 오류의 인증정보 보호를 포함했다.
