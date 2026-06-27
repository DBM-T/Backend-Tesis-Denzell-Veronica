import pytest
from types import SimpleNamespace
from collections import defaultdict, deque

from fastapi import HTTPException

from app.core import rate_limit


class FakeRequest:
    def __init__(self, host: str, path: str):
        self.client = SimpleNamespace(host=host)
        self.url = SimpleNamespace(path=path)


@pytest.mark.asyncio
async def test_auth_rate_limit_triggers_after_threshold(monkeypatch):
    monkeypatch.setattr(rate_limit, "_BUCKETS", defaultdict(deque))
    monkeypatch.setattr(rate_limit, "get_settings", lambda: SimpleNamespace(auth_rate_limit_per_minute=2))

    request = FakeRequest("127.0.0.1", "/auth/login")
    await rate_limit.auth_rate_limit(request)
    await rate_limit.auth_rate_limit(request)

    with pytest.raises(HTTPException) as exc:
        await rate_limit.auth_rate_limit(request)
    assert exc.value.status_code == 429
