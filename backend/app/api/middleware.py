"""Request id + access log for every request.

Each request gets an id (reused from an incoming X-Request-ID header, e.g. set by nginx,
otherwise generated). It is returned in the response header and attached to every log line
written while handling the request, so one request can be traced through the logs.
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

log = get_logger("http")

# Probes hit these every few seconds; logging them would drown out real traffic.
QUIET_PATHS = frozenset({"/healthz", "/readyz"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed", method=request.method, path=request.url.path)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 1)

        response.headers["X-Request-ID"] = request_id
        if request.url.path not in QUIET_PATHS:
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response
