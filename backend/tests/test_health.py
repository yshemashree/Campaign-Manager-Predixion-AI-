import asyncio

import httpx
from fastapi import FastAPI

from tests.conftest import failing, passing


async def test_healthz_is_ok_without_touching_dependencies(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.health_checks = {"database": failing()}  # liveness must not care

    resp = await client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_ready_when_all_checks_pass(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.health_checks = {"database": passing(), "redis": passing()}

    resp = await client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


async def test_readyz_503_names_the_failing_dependency(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.health_checks = {"database": passing(), "redis": failing()}

    resp = await client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json() == {"status": "not_ready", "checks": {"database": "ok", "redis": "fail"}}


async def test_readyz_treats_a_hanging_dependency_as_down(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async def hangs() -> None:
        await asyncio.sleep(5)  # longer than the 0.2 s test timeout

    app.state.health_checks = {"database": hangs}

    resp = await client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": "fail"}


async def test_request_id_is_generated_and_returned(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")

    assert len(resp.headers["x-request-id"]) == 32


async def test_incoming_request_id_is_kept(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz", headers={"X-Request-ID": "abc123"})

    assert resp.headers["x-request-id"] == "abc123"


async def test_openapi_spec_is_served(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/openapi.json")

    assert resp.status_code == 200
    assert {"/healthz", "/readyz"} <= set(resp.json()["paths"])
