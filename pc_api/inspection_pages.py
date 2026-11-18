"""Cursor-based pagination and short-lived snapshot cache for inspection list."""
from dataclasses import dataclass, field
import re
import secrets
import threading
import time

from pc_api.server import APIError

PAGE_TTL_SECONDS = 60.0
MAX_SNAPSHOTS_PER_SESSION = 2
MAX_SNAPSHOTS_TOTAL = 8
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
_CURSOR_RE = re.compile(r'^[A-Za-z0-9_-]{16,128}$')
_LIMIT_INT_RE = re.compile(r'^-?\d+$')
_ALLOWED_QUERY_KEYS = frozenset({'filter', 'limit', 'cursor'})


@dataclass
class _Snapshot:
    snapshot_id: str
    session_id: str | None
    path: str
    filter_val: str
    limit: int
    items: list
    all_total: int
    action_total: int
    created_at: float
    seq: int
    offset_tokens: dict[int, str] = field(default_factory=dict)


class InspectionPageCache:
    """Thread-safe in-memory snapshot cache for inspection list pagination."""

    def __init__(
        self,
        clock=time.monotonic,
        ttl_seconds: float = PAGE_TTL_SECONDS,
        max_per_session: int = MAX_SNAPSHOTS_PER_SESSION,
        max_total: int = MAX_SNAPSHOTS_TOTAL,
    ):
        self._lock = threading.Lock()
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._max_per_session = max_per_session
        self._max_total = max_total
        self._seq = 0
        self._snapshots: dict[str, _Snapshot] = {}
        self._cursors: dict[str, tuple[str, int]] = {}

    def _delete_snapshot_locked(self, snapshot_id: str) -> None:
        snap = self._snapshots.pop(snapshot_id, None)
        if snap is None:
            return
        for token in snap.offset_tokens.values():
            self._cursors.pop(token, None)

    def _evict_expired_locked(self, now: float) -> None:
        expired = [
            sid for sid, snap in self._snapshots.items()
            if now - snap.created_at >= self._ttl_seconds
        ]
        for sid in expired:
            self._delete_snapshot_locked(sid)

    def _evict_oldest_locked(self, candidates: list[_Snapshot], count: int) -> None:
        if count <= 0:
            return
        ordered = sorted(candidates, key=lambda s: (s.created_at, s.seq))
        for snap in ordered[:count]:
            self._delete_snapshot_locked(snap.snapshot_id)

    def _slice_locked(self, snap: _Snapshot, offset: int) -> dict:
        page_items = snap.items[offset:offset + snap.limit]
        next_offset = offset + snap.limit
        if next_offset < len(snap.items):
            next_cursor = snap.offset_tokens.get(next_offset)
            if next_cursor is None:
                next_cursor = secrets.token_urlsafe(24)
                snap.offset_tokens[next_offset] = next_cursor
                self._cursors[next_cursor] = (snap.snapshot_id, next_offset)
        else:
            next_cursor = None
        return {
            'items': page_items,
            'total': len(snap.items),
            'next_cursor': next_cursor,
            'all_total': snap.all_total,
            'action_total': snap.action_total,
        }

    def create_page(
        self,
        *,
        session_id: str | None,
        path: str,
        filter_val: str,
        limit: int,
        items: list,
        all_total: int,
        action_total: int,
    ) -> dict:
        with self._lock:
            now = self._clock()
            self._evict_expired_locked(now)

            same_session = [s for s in self._snapshots.values() if s.session_id == session_id]
            if len(same_session) >= self._max_per_session:
                self._evict_oldest_locked(same_session, len(same_session) - self._max_per_session + 1)

            if len(self._snapshots) >= self._max_total:
                self._evict_oldest_locked(
                    list(self._snapshots.values()),
                    len(self._snapshots) - self._max_total + 1,
                )

            self._seq += 1
            snapshot_id = secrets.token_urlsafe(16)
            snap = _Snapshot(
                snapshot_id=snapshot_id,
                session_id=session_id,
                path=path,
                filter_val=filter_val,
                limit=limit,
                items=items,
                all_total=all_total,
                action_total=action_total,
                created_at=now,
                seq=self._seq,
            )
            self._snapshots[snapshot_id] = snap
            return self._slice_locked(snap, 0)

    def get_page(
        self,
        *,
        session_id: str | None,
        path: str,
        filter_val: str,
        limit: int,
        cursor: str,
    ) -> dict:
        validate_cursor_format(cursor)
        with self._lock:
            now = self._clock()
            self._evict_expired_locked(now)

            entry = self._cursors.get(cursor)
            if entry is None:
                raise APIError(410, 'cursor_expired')
            snapshot_id, offset = entry
            snap = self._snapshots.get(snapshot_id)
            if snap is None:
                raise APIError(410, 'cursor_expired')
            if snap.session_id != session_id:
                raise APIError(404, 'not_found')
            if snap.path != path or snap.filter_val != filter_val or snap.limit != limit:
                raise APIError(400, 'invalid_request')
            return self._slice_locked(snap, offset)

    def discard_session(self, session_id: str | None) -> None:
        with self._lock:
            sids = [sid for sid, snap in self._snapshots.items() if snap.session_id == session_id]
            for sid in sids:
                self._delete_snapshot_locked(sid)

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()
            self._cursors.clear()


_DEFAULT_CACHE = InspectionPageCache()


def get_page_cache() -> InspectionPageCache:
    return _DEFAULT_CACHE


def discard_session_pages(session_id: str | None) -> None:
    _DEFAULT_CACHE.discard_session(session_id)


def validate_cursor_format(cursor) -> str:
    if not isinstance(cursor, str) or not _CURSOR_RE.fullmatch(cursor):
        raise APIError(400, 'invalid_request')
    return cursor


def parse_inspections_query(query: dict | None) -> tuple[str, int, str | None]:
    """Validate and normalize query parameters for GET /api/v1/inspections."""
    if query is None:
        return 'all', DEFAULT_LIMIT, None
    if not isinstance(query, dict) or (set(query) - _ALLOWED_QUERY_KEYS):
        raise APIError(400, 'invalid_request')

    filter_val = query.get('filter', 'all')
    if filter_val not in ('all', 'action'):
        raise APIError(400, 'invalid_request')

    raw_limit = query.get('limit')
    if raw_limit is None:
        limit_val = DEFAULT_LIMIT
    elif isinstance(raw_limit, bool):
        raise APIError(400, 'invalid_request')
    elif isinstance(raw_limit, int):
        limit_val = raw_limit
    elif isinstance(raw_limit, str) and _LIMIT_INT_RE.fullmatch(raw_limit):
        limit_val = int(raw_limit)
    else:
        raise APIError(400, 'invalid_request')

    if limit_val < 1 or limit_val > MAX_LIMIT:
        raise APIError(422, 'validation_failed')

    cursor = query.get('cursor')
    if cursor is not None:
        validate_cursor_format(cursor)

    return filter_val, limit_val, cursor
