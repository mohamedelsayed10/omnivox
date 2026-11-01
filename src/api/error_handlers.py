"""Maps exceptions to the standard JSON error body. Nothing internal leaks to clients."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config.logger import get_logger
from src.utils.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    GraphExecutionError,
    InvalidInputError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    NotFoundError,
    OmniVoxError,
    UnauthorizedError,
)

logger = get_logger(__name__)

UNKNOWN_REQUEST_ID = "-"
HTTP_STATUS_BY_ERROR: dict[type[OmniVoxError], int] = {
    InvalidInputError: 400,
    NotFoundError: 404,
    UnauthorizedError: 401,
    LLMRateLimitError: 429,
    LLMTimeoutError: 504,
    LLMError: 502,
    ExternalServiceError: 502,
    ConfigurationError: 503,
    GraphExecutionError: 500,
}
HTTP_CODES = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", UNKNOWN_REQUEST_ID)


def error_response(
    *, status: int, code: str, message: str, request_id: str, details: Any | None = None
) -> JSONResponse:
    """Build the standard error response."""
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details is not None:
        body["details"] = details
    return JSONResponse(
        status_code=status, content={"error": body}, headers={"X-Request-ID": request_id}
    )


def status_for(exc: OmniVoxError) -> int:
    """HTTP status for a domain error, resolved along its class hierarchy."""
    for cls in type(exc).__mro__:
        if cls in HTTP_STATUS_BY_ERROR:
            return HTTP_STATUS_BY_ERROR[cls]
    return 500


async def _domain_error(request: Request, exc: OmniVoxError) -> JSONResponse:
    logger.error("%s: %s", type(exc).__name__, exc, exc_info=exc)
    return error_response(
        status=status_for(exc),
        code=exc.code,
        message=exc.public_message,
        request_id=_request_id(request),
        details=exc.details,
    )


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    issues = [
        {"loc": [str(part) for part in err["loc"]], "msg": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    logger.info("Request validation failed: %d issue(s)", len(issues))
    return error_response(
        status=422,
        code="validation_error",
        message="The request failed validation.",
        request_id=_request_id(request),
        details=issues,
    )


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = HTTP_CODES.get(exc.status_code, "http_error")
    message = "The requested resource was not found." if exc.status_code == 404 else "HTTP error."
    return error_response(
        status=exc.status_code, code=code, message=message, request_id=_request_id(request)
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled %s: %s", type(exc).__name__, exc, exc_info=exc)
    return error_response(
        status=500,
        code="internal_error",
        message=OmniVoxError.default_message,
        request_id=_request_id(request),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install every handler on the app."""
    app.add_exception_handler(OmniVoxError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
