import asyncio
from typing import Any

import httpx
import pytest

import main

BODY: dict[str, Any] = {
    "app_config": {
        "app_id": "app",
        "app_version": 1,
        "app_type": "agent",
        "connection_config": {"connection_id": "c1", "agent_phone_number": "+918069000001"},
        "agent_variables": {"customer_name": "Priya"},
    },
    "user_config": {"user_phone_number": "+919876543210"},
    "webhook_config": {"url": "http://receiver.test/hook", "metadata": {"attempt_ref": "x"}},
}
URL = "/api/outbounds/v1/orgs/org-a/workspaces/ws-1/outbounds"


@pytest.fixture
async def client() -> Any:
    main.stats.clear()
    main.config = main.SimConfig(speed=1000, accept_latency_ms=0)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.json() == {"status": "ok"}


async def test_requires_api_key(client: httpx.AsyncClient) -> None:
    resp = await client.post(URL, json=BODY)
    assert resp.status_code == 401


async def test_rejects_malformed_body(client: httpx.AsyncClient) -> None:
    resp = await client.post(URL, json={"app_config": {}}, headers={"X-API-Key": "k"})
    assert resp.status_code == 422


async def test_accepts_call_and_sends_webhook(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        received.append(json.loads(request.content))
        return httpx.Response(200)

    monkeypatch.setattr(main, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    resp = await client.post(URL, json=BODY, headers={"X-API-Key": "k"})
    assert resp.status_code == 200
    attempt_id = resp.json()["attempt_id"]

    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.01)
    assert received[0]["attempt_id"] == attempt_id
    assert received[0]["status"] in {"connected", "busy", "no_answer", "failed"}
    assert received[0]["webhook_config"]["metadata"] == {"attempt_ref": "x"}


async def test_referee_measures_rolling_second(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await client.post(URL, json=BODY, headers={"X-API-Key": "k"})
    stats = (await client.get("/stats")).json()["org-a"]
    assert stats["total_requests"] == 3
    assert stats["max_calls_in_any_rolling_second"] == 3
    assert stats["max_concurrent_calls"] >= 1
