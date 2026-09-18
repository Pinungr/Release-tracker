"""Small in-process sliding-window rate limiter.

Applied to the endpoints that accept secrets (admin login, PIN verification,
my-bookings lookup) so they cannot be brute forced from a single client.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def client_key(request: Request, bucket: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{bucket}:{host}"


def enforce(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    key = client_key(request, bucket)
    now = time.monotonic()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = int(window_seconds - (now - hits[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait a moment and try again.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)


def reset() -> None:
    """Test helper."""
    with _lock:
        _hits.clear()
