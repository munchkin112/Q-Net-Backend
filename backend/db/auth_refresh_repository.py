"""리프레시 토큰 해시를 저장·조회하고 사용 기록을 남긴다. 트랜잭션은 호출하는 쪽에서 관리한다."""

from uuid import UUID

from psycopg import Connection

from backend.auth_refresh import create_refresh_token_hash


def create_auth_refresh_token(
    connection: Connection,
    session_id: UUID,
    token: str,
) -> dict:
    """서버에서 확인한 로그인 세션에 새 리프레시 토큰의 해시를 저장한다."""
    if not isinstance(session_id, UUID):
        raise ValueError("로그인 세션 ID가 유효하지 않습니다.")

    token_hash = create_refresh_token_hash(token)
    saved_token = connection.execute(
        """INSERT INTO auth_refresh_tokens (token_hash, session_id)
        VALUES (%s, %s)
        RETURNING token_hash, session_id, created_at, used_at""",
        (token_hash, session_id),
    ).fetchone()

    if saved_token is None:
        raise RuntimeError("리프레시 토큰을 저장할 수 없습니다.")

    return saved_token


def get_auth_refresh_token(
    connection: Connection,
    token: str,
) -> dict | None:
    """토큰과 연결된 세션 정보를 조회하고, 트랜잭션 종료까지 해당 행들을 잠근다."""
    token_hash = create_refresh_token_hash(token)
    return connection.execute(
        """SELECT
            refresh_token.token_hash,
            refresh_token.session_id,
            refresh_token.created_at,
            refresh_token.used_at,
            auth_session.user_id,
            auth_session.expires_at,
            auth_session.revoked_at
        FROM auth_refresh_tokens AS refresh_token
        JOIN auth_sessions AS auth_session
            ON auth_session.id = refresh_token.session_id
        WHERE refresh_token.token_hash = %s
        FOR UPDATE OF auth_session, refresh_token""",
        (token_hash,),
    ).fetchone()


def update_auth_refresh_token_usage(
    connection: Connection,
    session_id: UUID,
    token: str,
) -> bool:
    """해당 세션의 미사용 토큰에 사용 시각을 기록한다. 변경한 행이 없으면 False다."""
    if not isinstance(session_id, UUID):
        raise ValueError("로그인 세션 ID가 유효하지 않습니다.")

    token_hash = create_refresh_token_hash(token)
    saved_token = connection.execute(
        """UPDATE auth_refresh_tokens
        SET used_at = now()
        WHERE token_hash = %s
            AND session_id = %s
            AND used_at IS NULL
        RETURNING token_hash""",
        (token_hash, session_id),
    ).fetchone()

    return saved_token is not None