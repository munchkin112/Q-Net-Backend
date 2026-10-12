"""로컬 단일 서버에서 Google 로그인 요청을 임시 보관하고 검증한다."""

import secrets
from hashlib import sha256
from threading import Lock
from time import monotonic

from backend.auth_service import create_google_oauth_state


OAUTH_STATE_TTL_SECONDS = 300
MAX_PENDING_OAUTH_STATES = 1000

_oauth_states: dict[str, tuple[str, float]] = {}
_oauth_state_lock = Lock()


def create_google_oauth_transaction() -> tuple[str, str]:
    """state와 브라우저 확인값을 생성하고 5분 동안 임시 보관한다."""
    state = create_google_oauth_state()
    browser_token = secrets.token_urlsafe(32)
    browser_token_hash = sha256(browser_token.encode("utf-8")).hexdigest()
    now = monotonic()

    with _oauth_state_lock:
        expired_states = [
            saved_state
            for saved_state, (_, expires_at) in _oauth_states.items()
            if expires_at <= now
        ]
        for expired_state in expired_states:
            del _oauth_states[expired_state]

        if len(_oauth_states) >= MAX_PENDING_OAUTH_STATES:
            raise RuntimeError("로그인 요청이 많습니다. 잠시 후 다시 시도해주세요.")

        _oauth_states[state] = (
            browser_token_hash,
            now + OAUTH_STATE_TTL_SECONDS,
        )

    return state, browser_token


def validate_google_oauth_state(state: str, browser_token: str | None) -> None:
    """브라우저 확인값과 만료를 검사하고, 정상 요청은 한 번만 사용한다."""
    error_message = "로그인 요청이 유효하지 않습니다. 로그인을 다시 시작해주세요."

    if not isinstance(state, str) or not state or len(state) > 128:
        raise ValueError(error_message)
    if not isinstance(browser_token, str) or not browser_token:
        raise ValueError(error_message)
    if len(browser_token) > 128 or not browser_token.isascii():
        raise ValueError(error_message)

    browser_token_hash = sha256(browser_token.encode("utf-8")).hexdigest()

    with _oauth_state_lock:
        saved_state = _oauth_states.get(state)
        if saved_state is None:
            raise ValueError(error_message)

        saved_browser_token_hash, expires_at = saved_state
        if expires_at <= monotonic():
            del _oauth_states[state]
            raise ValueError(error_message)

        if not secrets.compare_digest(saved_browser_token_hash, browser_token_hash):
            raise ValueError(error_message)

        # 검증과 삭제를 같은 잠금 안에서 처리해 동시 재사용을 막는다.
        del _oauth_states[state]