"""공통 Bearer 인증 결과에서 현재 사용자의 DB UUID를 가져온다."""
from uuid import UUID

from backend.auth_dependencies import get_current_user as require_configured_user
from fastapi import HTTPException


def get_authenticated_user_id(current_user: object) -> UUID:
    """Bearer 검증 후 반환된 UUID 또는 AuthUserResponse.id를 사용한다."""
    value = current_user if isinstance(current_user, UUID) else getattr(current_user, 'id', None)
    if not isinstance(value, UUID):
        raise HTTPException(503, detail={'code': 'AUTH_CONTRACT_MISMATCH', 'message': '인증 사용자 ID 연결을 확인해주세요.'})
    return value
