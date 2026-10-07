"""확정된 일정 조회 API와 한국어 Swagger 문서를 제공한다."""

import os
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from backend.db.connection import database_connection
from backend.db.repository import get_schedules
from backend.schemas import ProfilePatch, ScheduleInput
from backend.exam_schemas import SubjectsInfo, PassCriteriaInfo, FeesInfo
from backend.services import list_certificates, certificate_detail
from backend.db.check import check_database


app = FastAPI(
    title="Q-Net 백엔드 API",
    version="0.1.0",
    description=(
        "확정된 DB 구조를 확인하는 초기 API입니다. "
        "서버 상태, 공식 종목 검색, 시험 상세정보와 단계별 일정 조회를 제공합니다. "
        "공식 상세정보를 수집한 종목의 시험과목·합격기준·응시료를 제공합니다. "
        "Render DB 연결 전에는 검색·일정 조회가 503을 반환합니다. "
        "아래 Schemas에서 프로필 부분 입력과 일정 구조도 확인할 수 있습니다. "
        "프로필 저장 HTTP API는 로그인 구현 후 연결하며, 북마크·응시조건 비교·Calendar·로드맵은 비활성 상태입니다."
    ),
    redoc_url=None,
)


class HealthResponse(BaseModel):
    """서버 실행 상태와 DB 연결정보 설정 여부를 나타낸다."""

    status: Literal["ok"]
    database_configured: bool


class DatabaseHealthResponse(BaseModel):
    """실제 DB 접속 여부와 필요한 테이블의 존재 여부를 나타낸다."""

    configured: bool
    connected: bool
    tables_ready: bool
    missing_tables: list[str]
    status: Literal["not_configured", "unavailable", "tables_missing", "ready"]


class ScheduleResponse(ScheduleInput):
    """DB에 저장된 시험 단계별 일정과 식별자를 반환한다."""

    id: UUID
    updated_at: datetime


class CertificateResponse(BaseModel):
    """검색에 필요한 공식 종목 정보와 출처를 반환한다."""

    id: UUID
    qnet_code: str
    name: str
    category: str
    career_tags: list[str]
    description: str | None
    source_url: str
    last_synced_at: datetime
    updated_at: datetime


class ExamInformationResponse(BaseModel):
    """정보 종류마다 확인 상태와 공식 출처·조회 시각을 반환한다."""

    subjects: SubjectsInfo
    pass_criteria: PassCriteriaInfo
    fees: FeesInfo
    retrieved_at: datetime | None
    updated_at: datetime | None


class CertificateDetailResponse(CertificateResponse):
    """종목 기본정보와 수집 여부를 구분한 시험 상세정보를 반환한다."""

    exam_information: ExamInformationResponse
    data_status: Literal["complete", "partial", "unavailable"]
    source_type: Literal["database", "none"]
    official_url: str
    message: str


@app.get("/health", tags=["서버 상태"], summary="서버 실행 확인")
def health() -> HealthResponse:
    """서버 실행과 연결정보 설정 여부를 확인한다. 실제 DB 접속 검사는 아니다."""
    return HealthResponse(status="ok", database_configured=bool(os.environ.get("DATABASE_URL")))


@app.get(
    "/health/database", response_model=DatabaseHealthResponse,
    tags=["서버 상태"], summary="실제 DB 접속과 초기 테이블 유무 확인",
    responses={503: {"model": DatabaseHealthResponse, "description": "설정·접속·테이블 준비 필요"}},
)
def database_health(response: Response) -> dict:
    """읽기 전용으로 접속을 검사하고 준비가 안 됐다면 503을 반환한다."""
    result = check_database()
    if not result["tables_ready"]:
        response.status_code = 503
    return result


@app.get(
    "/certificates", response_model=list[CertificateResponse],
    tags=["자격증 검색"], summary="공식 종목명·코드로 검색",
    responses={503: {"description": "Render DB 미설정 또는 조회 불가"}},
)
def certificates(
    q: str = Query(default="", max_length=100, description="종목명 일부 또는 공식 코드"),
    category: str | None = Query(default=None, min_length=1, max_length=10, description="공식 분류: T 기술자격, S 전문자격"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """공식 목록을 검색한다. 목록 존재가 현재 시행 여부나 응시 가능 판정을 뜻하지 않는다."""
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Render DATABASE_URL이 아직 설정되지 않았습니다.")
    try:
        return list_certificates(q.strip(), category, limit, offset)
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="DB에서 종목을 조회할 수 없습니다. 연결과 테이블 적용 상태를 확인해주세요.") from None


@app.get(
    "/certificates/{certificate_id}", response_model=CertificateDetailResponse,
    tags=["자격증 상세정보"], summary="시험과목·합격기준·응시료 조회",
    responses={404: {"description": "해당 종목이 없음"}, 503: {"description": "DB 조회 불가"}},
)
def detail(certificate_id: UUID) -> dict:
    """DB에 저장한 공식 자료를 조회하며 미수집 정보는 null과 확인 필요 상태로 반환한다."""
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Render DATABASE_URL이 아직 설정되지 않았습니다.")
    try:
        result = certificate_detail(certificate_id)
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="DB에서 상세정보를 조회할 수 없습니다. 연결과 테이블 적용 상태를 확인해주세요.") from None
    if result is None:
        raise HTTPException(status_code=404, detail="해당 자격증을 찾을 수 없습니다.")
    return result


@app.get(
    "/certificates/{certificate_id}/schedules",
    response_model=list[ScheduleResponse],
    tags=["시험일정"],
    summary="종목·연도별 필기·실기·면접 일정 조회",
    responses={503: {"description": "Render DB 미설정 또는 조회 불가"}},
)
def schedules(certificate_id: UUID, year: int = Query(ge=1900, le=9999)) -> list[dict]:
    """내부 자격증 UUID와 시행 연도로 조회하며 시험 단계마다 별도 행을 반환한다.

    실제 접수 가능 날짜는 registration_periods를 사용한다. 시작·종료 필드는 전체 범위다.
    빈 목록은 DB에 수집된 일정이 없다는 뜻이며 시험 미시행을 확정하지 않는다.
    상시검정의 지역·시험장별 일정은 별도 연동이 필요하다.
    """
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail="Render DATABASE_URL이 아직 설정되지 않았습니다.")
    try:
        with database_connection() as connection:
            return get_schedules(connection, certificate_id, year)
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="DB에서 일정을 조회할 수 없습니다. 연결과 테이블 적용 상태를 확인해주세요.") from None


def documented_openapi() -> dict:
    """미연결 프로필 입력 모델도 문서에서 검토할 수 있도록 추가한다."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    profile_schema = ProfilePatch.model_json_schema(ref_template="#/components/schemas/{model}")
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.update(profile_schema.pop("$defs", {}))
    components["ProfilePatch"] = profile_schema
    app.openapi_schema = schema
    return schema


app.openapi = documented_openapi
