# Q-Net-Backend

Q-Net 국가자격 시험정보·일정 코디네이터의 Python/FastAPI 백엔드다. 데이터베이스는 Render PostgreSQL을 사용한다.

## 현재 현황

- 공식 자격증 목록 613종목: 기술자격 513 + 전문자격 100.
- 기술자격 상세정보 510종목: 전체 정보 확보 464, 일부 미확인 46.
- 기술자격 시험일정 475종목·1,922단계: 필기·실기·면접, 분리된 접수기간과 빈자리 접수 지원.
- 검색·상세·일정 조회 API와 한국어 Swagger 제공.
- 전문자격 공식 원본과 계열 매핑은 사전 수집 자료로 준비한다. 남은 정규화·보완 수집과 Google 로그인·프로필 HTTP API·AI 기능은 확정 범위에 맞춰 연결한다.

세부 상태와 미연동 범위는 [작업 현황 표](docs/프로젝트_진행현황.md), [상세정보 결과](docs/기술자격_상세정보_확대결과.md), [시험일정 결과](docs/시험일정_연동_확대결과.md)를 확인한다.

2026-10-06 사전 준비: [데이터 준비 안내](docs/데이터_사전준비.md)에 재사용 데이터·누락 작업 목록·전문자격 원본 수집·프로젝트 당일 실행 순서를 정리했다. 로컬 준비 파일은 `research/preparation/`에 있으며, 과거 Render 저장 기록과 현재 로컬 검증 결과를 구분한다.

## 로컬 실행

저장소 루트에서 실행한다. 설치된 Python 3.11 이상을 사용한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
# backend/.env의 DATABASE_URL에 Render External Database URL을 입력한다.
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

기존 `backend/.env`가 있으면 복사 단계를 생략한다. 로컬 DB 연결은 SSL을 사용하며 서버·명령은 같은 설정 파일을 읽는다. 환경변수에 같은 값이 설정되어 있으면 환경변수를 우선한다. 설정 변경 후 서버를 재시작한다.

[Swagger](http://127.0.0.1:8000/docs)에서 자격증 검색으로 UUID를 얻고 상세·일정 API를 호출한다. 일정 조회에는 `year=2026`도 입력한다. DB와 서버 초기 적용·갱신 방법은 [백엔드 설명](backend/README.md)과 [일괄 수집 설명](docs/기술자격_일괄수집.md)을 따른다. 앱 실행이나 Git push만으로 DB 초기화·갱신이 실행되지는 않는다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

기본 테스트는 보관한 공식 응답으로 실행한다. 전용 PostgreSQL을 마련하고 `TEST_DATABASE_URL`을 설정하면 임시 스키마의 DB 통합 테스트도 실행한다. 미설정 시 해당 테스트는 생략된다.

## 문서

- [전체 작업 현황과 다음 순서](docs/프로젝트_진행현황.md)
- [API 설계와 실제 구현 범위](docs/API_설계_초안.md)
- [DB 설계와 적용된 테이블](docs/DB_설계_초안.md)
- [시험 상세정보 코드 설명](docs/시험_상세정보_연동.md)
- [공식 데이터 수집·갱신](docs/기술자격_일괄수집.md)
- [프로젝트 당일을 위한 데이터 사전 준비](docs/데이터_사전준비.md)
- [현재 요구사항](PRD.md)

## 협업

현재 개발 결과는 `dev`에서 공유한다. 기능별 브랜치에서 작업한 뒤 PR로 dev에 반영하고 검증된 배포 버전을 main에 반영한다. 팀원 초대와 리뷰 정책은 팀이 결정한다.
