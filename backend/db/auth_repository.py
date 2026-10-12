"""검증된 Google 계정으로 사용자를 조회·저장한다. DB 연결은 호출하는 쪽에서 관리한다."""

from uuid import UUID, uuid4

from psycopg import Connection

from backend.auth_identity import GoogleIdentity


def get_user(connection: Connection, user_id: UUID) -> dict | None:
    """서버에서 인증한 서비스 사용자 ID로 회원을 조회한다."""
    return connection.execute(
        """SELECT id, provider, provider_subject_id, email
        FROM users WHERE id = %s""",
        (user_id,),
    ).fetchone()


def get_user_by_google_subject(
    connection: Connection,
    provider_subject_id: str,
) -> dict | None:
    """검증된 Google sub로 회원을 조회하며, 이메일로 계정을 합치지 않는다."""
    return connection.execute(
        """SELECT id, provider, provider_subject_id, email
        FROM users WHERE provider = %s AND provider_subject_id = %s""",
        ("google", provider_subject_id),
    ).fetchone()


def create_user(connection: Connection, identity: GoogleIdentity) -> dict:
    """검증된 Google 계정을 저장한다. 같은 계정이 이미 있으면 기존 ID를 유지한다."""
    saved_user = connection.execute(
        """INSERT INTO users (id, provider, provider_subject_id, email)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (provider, provider_subject_id) DO UPDATE SET
            email = COALESCE(EXCLUDED.email, users.email),
            updated_at = now()
        RETURNING id, provider, provider_subject_id, email""",
        (
            uuid4(),
            "google",
            identity.provider_subject_id,
            identity.email,
        ),
    ).fetchone()

    if saved_user is None:
        raise RuntimeError("사용자 정보를 저장할 수 없습니다.")

    return saved_user