from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


_BUCKETS: dict[str, Deque[float]] = defaultdict(deque)
_LOCK = asyncio.Lock()


async def auth_rate_limit(request: Request) -> None:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    bucket_key = f"{client_ip}:{request.url.path}"
    now = time.monotonic()
    window = 60.0

    async with _LOCK:
        bucket = _BUCKETS[bucket_key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= settings.auth_rate_limit_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos. Intenta nuevamente mas tarde.",
            )
        bucket.append(now)
