# Q-Net-Backend

관심 분야 기반 자격증 탐색 서비스의 FastAPI 백엔드다. DB는 기존 Render PostgreSQL을 사용한다.

## main에 포함된 공통 기반

| 항목 | 제공 범위 |
| --- | --- |
| FastAPI | 앱 실행, `/health`, `/health/database`, `/docs` |
| Render | `render.yaml`, Python 버전, 빌드·실행 명령 |
| PostgreSQL | 환경변수 기반 연결, 읽기 전용 연결·테이블 검사 |
| Agent | `backend/agent/` 패키지, LangGraph·LangChain 의존성 |
| 환경변수 | `backend/.env.example`에 변수명·설명만 제공 |

자격증 검색·상세·일정 수집과 조회 코드는 현재 `dev`에 있다. Google 로그인·프로필 API·추천 Agent·Calendar는 담당자의 기능 브랜치에서 구현한다. `main`의 Agent 폴더에는 아직 실행 Graph가 없다.

## 개발환경 준비

Windows PowerShell에서 저장소 루트 기준으로 실행한다.

```powershell
git clone --branch main https://github.com/munchkin112/Q-Net-Backend.git
cd Q-Net-Backend

# uv가 없으면 한 번 설치한다.
python -m pip install uv
uv --version

# .python-version에 지정된 Python으로 가상환경을 만든다.
uv venv
uv pip install -r backend/requirements.txt

# 기존 설정은 유지하고 파일이 없을 때만 복사한다.
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
```

`uv venv`는 필요하면 지정된 Python을 내려받는다. 현재는 `requirements.txt` 방식으로 관리하며 패키지가 바뀌면 설치 명령을 다시 실행한다. 별도로 가상환경을 활성화하지 않아도 아래 `uv run`으로 실행할 수 있다.

## 환경변수

`backend/.env`에 로컬 설정을 넣는다. 배포에서는 Render 대시보드 환경변수로 설정한다. 이미 설정된 실행 환경의 값을 `.env`가 덮어쓰지 않는다.

| 변수 | 용도 | 현재 사용 여부 |
| --- | --- | --- |
| `DATABASE_URL` | Render PostgreSQL 연결 URL | DB 연결 확인에서 사용 |
| `QNET_SERVICE_KEY` | 공공데이터포털 인증키 | 수집 기능에서 연결 예정 |
| `OPENAI_API_KEY` | OpenAI를 선택할 경우 LLM 인증 | Agent 구현 시 연결 |
| `GOOGLE_CLIENT_ID` | Google OAuth 클라이언트 ID | 로그인·Calendar 구현 시 연결 |
| `GOOGLE_CLIENT_SECRET` | Google OAuth 서버 인증정보 | 로그인·Calendar 구현 시 연결 |
| `GOOGLE_REDIRECT_URI` | Google 인증 완료 콜백 URL | API 계약에 맞춰 설정 |

로컬에서는 Render **External Database URL**에 `sslmode=require`를 적용한다. Render 배포 서버에서는 DB가 제공하는 **Internal Database URL**을 사용한다. 실제 키·비밀번호·토큰·`.env`는 Git에 올리지 않는다. LLM 제공자가 바뀌면 해당 담당자가 필요한 변수만 추가한다.

## 로컬 실행과 확인

```powershell
uv run python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

- [Swagger 문서](http://127.0.0.1:8000/docs)
- [서버 실행 확인](http://127.0.0.1:8000/health): DB 설정이 없어도 HTTP 200을 반환한다.
- [DB 확인](http://127.0.0.1:8000/health/database): 접속과 기존 필수 테이블을 검사한다. 미준비 상태는 HTTP 503이다.

서버 종료는 `Ctrl+C`다. 이 공통 기반은 DB를 자동으로 생성하거나 변경하지 않는다. 공용 DB 스키마 변경은 DB 담당자가 취합해 적용한다.

```powershell
uv run python -m unittest discover -s backend/tests
uv run python -m backend.db.check
```

DB 검사 명령은 설정·접속·필수 테이블이 준비되지 않았으면 실패 코드로 종료한다.

## Render 배포 설정

배포 담당자가 `render.yaml`을 사용하거나 Web Service에 아래 값을 입력한다. Python 버전은 `.python-version`과 `PYTHON_VERSION`을 동일하게 유지한다.

| 설정 | 값 |
| --- | --- |
| 배포 브랜치 | `main` |
| Runtime | Python |
| Root Directory | 저장소 루트, 별도 지정하지 않음 |
| Build Command | `pip install -r backend/requirements.txt` |
| Start Command | `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` |
| 환경변수 | 대시보드에 실제 `DATABASE_URL` 입력 |

Blueprint에는 새 PostgreSQL 생성 설정이 없다. 기존 DB를 연결한다. 로컬 개발의 `--reload` 옵션은 배포 명령에 넣지 않는다. 이번 반영은 배포 설정 준비이며 실제 Render 서비스 생성·배포는 별도다.

## 팀 작업 흐름

```text
main 공통 기반 → 각자 기능 브랜치 → dev에서 통합·검증 → main 반영
```

```powershell
git switch main
git pull origin main
git switch -c feature/google-login
```

브랜치명은 맡은 기능으로 바꾼다. 기존 조회 API가 필요한 담당자는 `dev`에서 분기한다. 새 main 기반을 기존 dev에 반영할 때 `backend/main.py`와 README는 기존 기능을 유지하도록 병합하며 main 파일로 통째로 덮어쓰지 않는다.

- [팀 공유 문서](docs/팀_공유문서.md): 기능·API 계약·DB·데이터 수집 현황
- [제품 요구사항](PRD.md): 원문 이후 사용자 확정사항이 우선
- [구현 규칙](AGENTS.md)
- [Agent 폴더 안내](backend/agent/README.md)
- [Render Blueprint 공식 문서](https://render.com/docs/blueprint-spec)
- [Render Python 버전 안내](https://render.com/docs/python-version)
