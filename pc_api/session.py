"""In-memory launch-key exchange and session/CSRF management for PC API."""

import secrets
import threading
import time

LAUNCH_KEY_TTL_SECONDS = 60.0
SESSION_TTL_SECONDS = 8 * 3600.0
SESSION_COOKIE_NAME = 'pc_session'


def parse_session_cookie(cookie_headers: list[str], name: str = SESSION_COOKIE_NAME) -> str | None:
    """Extract a single session cookie value from Cookie header lines."""
    found: list[str] = []
    for header in cookie_headers:
        for part in header.split(';'):
            item = part.strip()
            if not item or '=' not in item:
                continue
            key, _, val = item.partition('=')
            if key.strip() == name:
                found.append(val.strip())
    if len(found) != 1 or not found[0] or not found[0].isascii():
        return None
    return found[0]


def build_session_cookie(session_id: str) -> str:
    return f'{SESSION_COOKIE_NAME}={session_id}; HttpOnly; SameSite=Strict; Path=/'


def build_clear_session_cookie() -> str:
    return f'{SESSION_COOKIE_NAME}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'


class SessionStore:
    """Thread-safe store for one-time launch keys and 8-hour PC sessions."""

    def __init__(
        self,
        clock=time.monotonic,
        *,
        launch_ttl: float = LAUNCH_KEY_TTL_SECONDS,
        session_ttl: float = SESSION_TTL_SECONDS,
    ):
        self._clock = clock
        self._launch_ttl = float(launch_ttl)
        self._session_ttl = float(session_ttl)
        self._lock = threading.Lock()
        self._launch_keys: dict[str, float] = {}
        self._sessions: dict[str, tuple[str, float]] = {}

    def _prune_expired(self, now: float) -> None:
        self._launch_keys = {k: exp for k, exp in self._launch_keys.items() if now <= exp}
        self._sessions = {sid: pair for sid, pair in self._sessions.items() if now <= pair[1]}

    def issue_launch_key(self) -> str:
        key = secrets.token_hex(32)
        now = self._clock()
        with self._lock:
            self._prune_expired(now)
            self._launch_keys[key] = now + self._launch_ttl
        return key

    def exchange_launch_key(self, launch_key: str) -> tuple[str, str] | None:
        """Consume a valid launch key in constant time and create a (session_id, csrf_token)."""
        if not isinstance(launch_key, str) or not launch_key or not launch_key.isascii():
            return None
        now = self._clock()
        with self._lock:
            matched_key: str | None = None
            matched_exp = 0.0
            for candidate, exp in list(self._launch_keys.items()):
                if secrets.compare_digest(candidate, launch_key):
                    matched_key = candidate
                    matched_exp = exp
            if matched_key is None:
                return None
            del self._launch_keys[matched_key]
            if now > matched_exp:
                return None
            session_id = secrets.token_hex(32)
            csrf_token = secrets.token_hex(32)
            self._sessions[session_id] = (csrf_token, now + self._session_ttl)
            return session_id, csrf_token

    def get_session_csrf(self, session_id: str | None) -> str | None:
        """Return the CSRF token for an active, unexpired session, else None."""
        if not isinstance(session_id, str) or not session_id or not session_id.isascii():
            return None
        now = self._clock()
        with self._lock:
            matched_sid: str | None = None
            matched_pair: tuple[str, float] | None = None
            for candidate, pair in list(self._sessions.items()):
                if secrets.compare_digest(candidate, session_id):
                    matched_sid = candidate
                    matched_pair = pair
            if matched_sid is None or matched_pair is None:
                return None
            csrf_token, exp = matched_pair
            if now > exp:
                del self._sessions[matched_sid]
                return None
            return csrf_token

    def verify_csrf(self, session_id: str | None, csrf_token: str | None) -> bool:
        if not isinstance(csrf_token, str) or not csrf_token or not csrf_token.isascii():
            return False
        expected = self.get_session_csrf(session_id)
        if expected is None:
            return False
        return secrets.compare_digest(expected, csrf_token)

    def revoke_session(self, session_id: str | None) -> bool:
        if not isinstance(session_id, str) or not session_id or not session_id.isascii():
            return False
        with self._lock:
            matched_sid: str | None = None
            for candidate in list(self._sessions.keys()):
                if secrets.compare_digest(candidate, session_id):
                    matched_sid = candidate
            if matched_sid is None:
                return False
            del self._sessions[matched_sid]
            return True

    def clear(self) -> None:
        with self._lock:
            self._launch_keys.clear()
            self._sessions.clear()
