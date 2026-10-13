"""사용자가 선택한 일정만 기본 Google Calendar에 등록하는 API다."""

import logging
from collections.abc import Callable
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException

from backend.calendar_auth_dependencies import require_calendar_connection
from backend.calendar_schemas import CalendarRegisterRequest, CalendarRegisterResponse
from backend.calendar_registration_service import (
    CalendarRegistrationError,
    register_calendar_events,
)


logger = logging.getLogger(__name__)


def create_calendar_router(
    current_calendar_connection_dependency: Callable = require_calendar_connection,
    register_events: Callable = register_calendar_events,
) -> APIRouter:
    """Calendar 전용 연결 확인과 등록 처리를 제공하는 라우터를 만든다."""
    router = APIRouter(tags=["Google Calendar"])

    @router.post(
        "/calendar/register",
        response_model=CalendarRegisterResponse,
        summary="사용자가 선택한 시험 일정을 Google Calendar에 등록",
        responses={
            401: {"description": "Google Calendar 연결이 필요하거나 만료됨"},
            403: {"description": "Google Calendar 권한이 없음"},
            409: {"description": "멱등 키 충돌 또는 일정 변경"},
            422: {"description": "요청 일정에 등록 가능한 날짜가 없음"},
            503: {"description": "DB 또는 Google 연동을 사용할 수 없음"},
        },
    )
    def create_calendar_registration(
        request: CalendarRegisterRequest,
        idempotency_key: UUID = Header(alias="Idempotency-Key"),
        connection_id: UUID = Depends(current_calendar_connection_dependency),
    ) -> dict:
        """선택 항목만 검증·등록하고 항목별 성공·실패 결과를 반환한다."""
        try:
            return register_events(connection_id, request, idempotency_key)
        except CalendarRegistrationError as error:
            raise HTTPException(
                error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from None
        except psycopg.Error as error:
            # 원문 SQL·토큰·접속정보 없이 실패 위치만 서버 로그에 남긴다.
            logger.error(
                "Calendar DB failure: type=%s sqlstate=%s table=%s column=%s constraint=%s",
                type(error).__name__, error.sqlstate,
                error.diag.table_name, error.diag.column_name, error.diag.constraint_name,
            )
            raise HTTPException(
                503,
                detail={"code": "CALENDAR_DATABASE_UNAVAILABLE", "message": "Calendar 정보를 저장할 수 없습니다."},
            ) from None
        except RuntimeError:
            raise HTTPException(
                503,
                detail={"code": "CALENDAR_CONFIGURATION_UNAVAILABLE", "message": "Google Calendar 설정을 확인해야 합니다."},
            ) from None

    return router

