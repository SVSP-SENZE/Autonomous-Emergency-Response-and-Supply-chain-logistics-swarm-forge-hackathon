"""Application error types and a consistent error-response format.

Every error returned by the API uses the same envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "Relief centre 99 not found",
    "details": {}
  }
}
```
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class BadRequestError(AppError):
    """Invalid operation or payload semantics (HTTP 400)."""

    status_code = 400
    code = "bad_request"


class NotFoundError(AppError):
    """Resource does not exist (HTTP 404)."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """Operation conflicts with current state (HTTP 409)."""

    status_code = 409
    code = "conflict"


class ServiceUnavailableError(AppError):
    """An upstream dependency failed; retried later may succeed (HTTP 503)."""

    status_code = 503
    code = "service_unavailable"


class AiError(AppError):
    """Base for AI provider application errors."""


class AiNotConfiguredError(AiError):
    """The AI provider is enabled but the API key is missing (HTTP 503)."""

    status_code = 503
    code = "ai_not_configured"


class AiUpstreamError(AiError):
    """AI provider upstream unavailable / auth / model error (HTTP 502)."""

    status_code = 502
    code = "ai_upstream_error"


class AiQuotaError(AiError):
    """Upstream quota or rate limit exhausted (HTTP 429)."""

    status_code = 429
    code = "ai_quota_exceeded"


class AgentToolError(AiError):
    """A tool call failed (validation, unknown tool, handler exception)."""

    status_code = 400
    code = "agent_tool_error"


def _error_payload(
    code: str, message: str, details: dict[str, Any] | list[Any] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach consistent error handlers to the FastAPI application."""

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Sanitised field errors; never leak raw exception context.
        field_errors = [
            {
                "loc": [str(loc) for loc in error.get("loc", [])],
                "msg": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                code="validation_error",
                message="Request validation failed.",
                details=field_errors,
            ),
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("Database integrity error: %s", exc.orig)
        return JSONResponse(
            status_code=409,
            content=_error_payload(
                code="conflict",
                message="The request conflicts with existing data.",
            ),
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                code="database_error",
                message="A database error occurred.",
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {404: "not_found", 401: "unauthorized", 403: "forbidden", 405: "method_not_allowed"}
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(
                code=code_map.get(exc.status_code, "http_error"),
                message=str(exc.detail),
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # Log internally, never expose stack traces through the API.
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                code="internal_error",
                message="An unexpected error occurred.",
            ),
        )


__all__ = [
    "AgentToolError",
    "AiError",
    "AiNotConfiguredError",
    "AiQuotaError",
    "AiUpstreamError",
    "AppError",
    "BadRequestError",
    "NotFoundError",
    "ConflictError",
    "register_exception_handlers",
    "jsonable_encoder",
]
