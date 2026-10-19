from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.shared.responses import error_response


class AppException(Exception):
    """业务异常基类。

    ``error_code`` 是给程序判断的稳定字符串码（取值见
    ``app.modules.agent_runtime.error_codes.ErrorCode``）；``code`` 字段仍是
    HTTP 状态码，语义不变。未指定 ``error_code`` 时 REST 响应里该字段为
    ``null``，调用方据此回落到状态码判断。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        headers: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.headers = headers
        self.error_code = error_code


class NotFoundException(AppException):
    def __init__(self, message: str = "resource not found") -> None:
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)


class ConflictException(AppException):
    def __init__(self, message: str = "resource conflict") -> None:
        super().__init__(message, status_code=status.HTTP_409_CONFLICT)


class BadRequestException(AppException):
    def __init__(self, message: str = "bad request") -> None:
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "unauthorized") -> None:
        super().__init__(
            message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )


class TooManyRequestsException(AppException):
    def __init__(self, message: str = "too many requests") -> None:
        super().__init__(message, status_code=status.HTTP_429_TOO_MANY_REQUESTS)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def handle_app_exception(
        request: Request, exc: AppException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(
                message=exc.message, code=exc.status_code, error_code=exc.error_code
            ).model_dump(),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(
                message="internal server error",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ).model_dump(),
        )
