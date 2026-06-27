import pytest

from app.services import health_service


@pytest.mark.asyncio
async def test_health_returns_ok(client, monkeypatch):
    async def fake_verify() -> None:
        return None

    monkeypatch.setattr(health_service, "verify_supabase_connection", fake_verify)
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["supabase"] == "connected"
