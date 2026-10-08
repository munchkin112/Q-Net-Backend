# Q-Net-Backend

현재 `main`은 문서와 환경설정 예시만 공유합니다. 실행 코드는 [dev 브랜치](https://github.com/munchkin112/Q-Net-Backend/tree/dev)에 있으며, 개발·서버 실행은 `dev`에서 진행합니다. 실제 `.env`와 인증정보는 포함하지 않습니다.

Q-Net 국가자격 시험정보·일정 코디네이터의 Python/FastAPI 백엔드다. DB는 Render PostgreSQL을 사용한다.

**팀 공유는 [팀 공유 문서](docs/팀_공유문서.md) 하나를 기준으로 한다.**

실행·테스트, 진행 현황, 구현된 API와 구현 예정 API, 로그인·Calendar 담당 범위, 함수명 규칙, DB 구조, 데이터 수집·예외처리 증빙을 통합했다. 세부 원본과 검증 로그는 문서 안의 링크에서 확인한다.

- [제품 요구사항](PRD.md)
- [프로젝트 구현 규칙](AGENTS.md)

개발 작업은 기능 브랜치에서 진행하고 PR로 dev에 병합한다. 서버 실행·환경변수 설정·DB 적용은 팀 공유 문서의 해당 절차를 따른다.
