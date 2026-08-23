"""Centralized application errors and FastAPI exception handlers."""
from __future__ import annotations

from typing import Any, Optional
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.contracts import fail

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base application exception with typed error code and status."""

    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(self, message: str, *, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.details = details


class BadRequestError(AppError):
    code = "BAD_REQUEST"
    status_code = 400


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class DependencyError(AppError):
    code = "DEPENDENCY_ERROR"
    status_code = 503


class ExchangeUnavailableError(AppError):
    code = "EXCHANGE_UNAVAILABLE"
    status_code = 503


class UpstreamError(AppError):
    code = "UPSTREAM_ERROR"
    status_code = 502


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    status_code = 500


def register_exception_handlers(app: FastAPI) -> None:
    """Register consistent API error responses."""

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(exc.code, exc.message, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=fail("VALIDATION_ERROR", "Request validation failed", details=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=fail("INTERNAL_ERROR", "服务器内部错误，请稍后重试"),
        )
