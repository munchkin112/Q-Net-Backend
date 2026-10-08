# Q-Net-Backend

현재 `main`은 문서와 환경설정 예시만 공유합니다. 실행 코드는 [dev 브랜치](https://github.com/munchkin112/Q-Net-Backend/tree/dev)에 있으며, 개발·서버 실행은 `dev`에서 진행합니다. 실제 `.env`와 인증정보는 포함하지 않습니다.

Q-Net 국가자격 시험정보·일정 코디네이터의 Python/FastAPI 백엔드다. DB는 Render PostgreSQL을 사용한다.

**팀 공유는 [팀 공유 문서](docs/팀_공유문서.md) 하나를 기준으로 한다.**

실행·테스트, 진행 현황, 구현된 API와 구현 예정 API, 로그인·Calendar 담당 범위, 함수명 규칙, DB 구조, 데이터 수집·예외처리 증빙을 통합했다. 세부 원본과 검증 로그는 문서 안의 링크에서 확인한다.

- [제품 요구사항](PRD.md)
- [프로젝트 구현 규칙](AGENTS.md)

개발 작업은 기능 브랜치에서 진행하고 PR로 dev에 병합한다. 서버 실행·환경변수 설정·DB 적용은 팀 공유 문서의 해당 절차를 따른다.

## uv로 개발환경 준비하기

Windows PowerShell 기준이다. 실행 코드는 `dev`에 있으므로 처음 받는 경우 아래 명령으로 시작한다.

```powershell
git clone --branch dev https://github.com/munchkin112/Q-Net-Backend.git
cd Q-Net-Backend
```

이미 저장소가 있다면 해당 저장소 루트에서 진행한다. `main`에는 안내 문서와 설정 예시만 있으므로 서버 실행은 `dev`에서 한다.

```powershell
# uv가 없을 때 한 번 설치한다. Python이 먼저 설치되어 있어야 한다.
python -m pip install uv
uv --version

# .venv가 없는 첫 설정 때 가상환경을 만든다.
uv venv

# 필요한 패키지를 가상환경에 설치한다.
uv pip install -r backend/requirements.txt

# 기존 .env는 유지하고, 없을 때만 예시를 복사한다.
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
```

`backend/.env`의 `DATABASE_URL`에 Render **External Database URL**을 입력하고 로컬 접속에 `sslmode=require`를 사용한다. 실제 DB 주소·비밀번호·토큰은 Git에 올리지 않는다.

```powershell
# 가상환경을 따로 활성화하지 않고 서버를 실행한다.
uv run python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

실행 후 [Swagger](http://127.0.0.1:8000/docs)에서 API를 확인한다. 서버 종료는 `Ctrl+C`다.

```powershell
# DB 연결 확인 / 백엔드 테스트
uv run python -m backend.db.check
uv run python -m unittest discover -s backend/tests
```

현재는 `requirements.txt` 방식이므로 패키지 목록이 바뀌면 `uv pip install -r backend/requirements.txt`를 다시 실행한다. 공용 DB 초기화는 개발환경 준비에 포함하지 않는다.

참고: [uv 공식 환경설정 안내](https://docs.astral.sh/uv/pip/environments/), [uv 실행 명령 안내](https://docs.astral.sh/uv/reference/cli/#uv-run).
