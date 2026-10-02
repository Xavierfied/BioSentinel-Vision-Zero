"""Small in-memory sliding-window rate limiter.

Good enough for a single-process deployment. Behind several workers or
machines, swap the store for Redis; the dependency interface stays the same.
"""

import math
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Callable, Deque, Dict

from fastapi import HTTPException, Request, status

from app.security.net import get_client_ip


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: float) -> float:
        """Record a hit. Returns 0 if allowed, else seconds until a slot frees."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return window_seconds - (now - hits[0])
            hits.append(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def enforce(key: str, limit: int, window_seconds: float = 60.0) -> None:
    retry_after = limiter.hit(key, limit, window_seconds)
    if retry_after > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Slow down and try again shortly.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )


def limit_per_ip(scope: str, limit_getter: Callable[[], int]):
    """FastAPI dependency: at most ``limit_getter()`` requests a minute per IP."""

    async def dependency(request: Request) -> None:
        enforce(f"{scope}:ip:{get_client_ip(request)}", limit_getter())

    return dependency
