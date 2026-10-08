"""팀 공통 FastAPI 실행과 읽기 전용 DB 상태 확인을 제공한다."""

import os
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel

from backend.db.check import check_database


app = FastAPI(
    title="Q-Net 백엔드 API",
    version="0.1.0",
    description="팀 공통 개발 기반입니다. 자격증 조회·추천·Google 연동은 기능 브랜치에서 연결합니다.",
    redoc_url=None,
)


class HealthResponse(BaseModel):
    """앱 실행과 DB 환경변수 설정 여부를 나타낸다."""

    status: Literal["ok"]
    database_configured: bool


class DatabaseHealthResponse(BaseModel):
    """DB 연결과 기존 필수 테이블 준비 상태를 나타낸다."""

    configured: bool
    connected: bool
    tables_ready: bool
    missing_tables: list[str]
    status: Literal["not_configured", "unavailable", "tables_missing", "ready"]


@app.get("/health", tags=["서버 상태"], summary="서버 실행 확인")
def get_health() -> HealthResponse:
    """DB가 아직 설정되지 않아도 앱 실행 상태를 반환한다."""
    return HealthResponse(status="ok", database_configured=bool(os.environ.get("DATABASE_URL")))


@app.get(
    "/health/database", response_model=DatabaseHealthResponse,
    tags=["서버 상태"], summary="DB 연결과 필수 테이블 확인",
    responses={503: {"model": DatabaseHealthResponse, "description": "DB 설정·접속·테이블 준비 필요"}},
)
def get_database_health(response: Response) -> dict:
    """테이블을 생성하거나 변경하지 않고 DB 상태만 조회한다."""
    result = check_database()
    if not result["tables_ready"]:
        response.status_code = 503
    return result
