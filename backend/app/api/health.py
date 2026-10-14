"""Liveness and readiness endpoints.

/healthz  "is the process alive?"  Never touches dependencies, so a slow database can't
          make the orchestrator restart a healthy API.
/readyz   "can it do useful work?"  Checks Postgres and Redis. Returns 503 if any is down,
          so traffic is held back until the dependencies are reachable.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.core.logging import get_logger

HealthCheck = Callable[[], Awaitable[None]]

router = APIRouter(tags=["health"])
log = get_logger(__name__)


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "fail"]]


@router.get("/healthz", response_model=LivenessResponse)
async def healthz() -> LivenessResponse:
    return LivenessResponse(status="ok")


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A dependency is down"}},
)
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    checks: dict[str, HealthCheck] = request.app.state.health_checks
    timeout: float = request.app.state.settings.health_check_timeout_s

    async def run(name: str, check: HealthCheck) -> tuple[str, bool]:
        try:
            await asyncio.wait_for(check(), timeout=timeout)
            return name, True
        except Exception as exc:  # any failure, including timeout, means "not ready"
            log.warning("readiness_check_failed", check=name, error=repr(exc))
            return name, False

    results = await asyncio.gather(*(run(name, check) for name, check in checks.items()))
    statuses: dict[str, Literal["ok", "fail"]] = {
        name: "ok" if ok else "fail" for name, ok in results
    }
    ready = all(ok for _, ok in results)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "not_ready", checks=statuses)
