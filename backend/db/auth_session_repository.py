"""로그인 세션을 생성·조회·검사·폐기한다. DB 연결과 저장 확정은 호출하는 쪽에서 관리한다."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from psycopg import Connection


def create_auth_session(
    connection: Connection,
    user_id: UUID,
    expires_at: datetime | None,
) -> dict:
    """회원에게 만료시각이 있거나 로그아웃 때까지 유지되는 세션을 생성한다."""
    if not isinstance(user_id, UUID):
        raise ValueError("로그인 세션을 생성할 회원 ID가 유효하지 않습니다.")

    if (
        expires_at is not None
        and (
            not isinstance(expires_at, datetime)
            or expires_at.utcoffset() is None
            or expires_at <= datetime.now(timezone.utc)
        )
    ):
        raise ValueError("세션 만료시각은 없거나 시간대가 포함된 미래 시각이어야 합니다.")

    session = connection.execute(
        """INSERT INTO auth_sessions (id, user_id, expires_at)
        VALUES (%s, %s, %s)
        RETURNING id, user_id, created_at, expires_at, revoked_at""",
        (
            uuid4(),
            user_id,
            expires_at.astimezone(timezone.utc) if expires_at is not None else None,
        ),
    ).fetchone()

    if session is None:
        raise RuntimeError("로그인 세션을 저장할 수 없습니다.")

    return session


def get_auth_session(
    connection: Connection,
    session_id: UUID,
    user_id: UUID,
) -> dict | None:
    """서버에서 인증한 회원에게 속한 세션을 조회한다. 상태 검사는 별도로 수행한다."""
    return connection.execute(
        """SELECT id, user_id, created_at, expires_at, revoked_at
        FROM auth_sessions
        WHERE id = %s AND user_id = %s""",
        (session_id, user_id),
    ).fetchone()


def validate_auth_session(
    session: dict | None,
    session_id: UUID,
    user_id: UUID,
) -> dict:
    """토큰의 회원·세션 ID와 일치하고 만료·폐기되지 않은 세션만 반환한다."""
    error_message = "로그인 세션이 유효하지 않습니다. 다시 로그인해주세요."

    if (
        not isinstance(session_id, UUID)
        or not isinstance(user_id, UUID)
        or not isinstance(session, dict)
        or session.get("id") != session_id
        or session.get("user_id") != user_id
        or "expires_at" not in session
        or "revoked_at" not in session
        or session["revoked_at"] is not None
    ):
        raise ValueError(error_message)

    expires_at = session.get("expires_at")
    if expires_at is not None:
        if (
            not isinstance(expires_at, datetime)
            or expires_at.utcoffset() is None
            or expires_at <= datetime.now(timezone.utc)
        ):
            raise ValueError(error_message)

    return session


def update_auth_session_revocation(
    connection: Connection,
    session_id: UUID,
    user_id: UUID,
) -> bool:
    """해당 회원의 세션을 폐기한다. 이미 폐기한 세션의 종료시각은 유지한다."""
    session = connection.execute(
        """UPDATE auth_sessions
        SET revoked_at = COALESCE(revoked_at, now())
        WHERE id = %s AND user_id = %s
        RETURNING id""",
        (session_id, user_id),
    ).fetchone()

    return session is not None
