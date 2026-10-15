"""Errors in one consistent JSON shape (RFC 9457 "problem details").

    {"type": "about:blank", "title": "Not Found", "status": 404, "detail": "Campaign not found"}

Validation errors also list each field that failed, so the UI can show them next to inputs.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    title: str = "Bad Request"

    def __init__(self, detail: str, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Not Found"


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    title = "Conflict"


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Forbidden"


class Unauthorized(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    title = "Unauthorized"


class Unprocessable(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    title = "Unprocessable Content"


def problem(
    status_code: int, title: str, detail: str, errors: list[dict[str, Any]] | None = None
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if errors is not None:
        body["errors"] = errors
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return problem(exc.status_code, exc.title, exc.detail, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(p) for p in err["loc"] if p != "body"),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return problem(422, "Unprocessable Content", "Request validation failed", errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, str(exc.detail), str(exc.detail))
