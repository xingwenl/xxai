from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.shared.responses import error_response


class AppException(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFoundException(AppException):
    def __init__(self, message: str = "resource not found") -> None:
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)


class ConflictException(AppException):
    def __init__(self, message: str = "resource conflict") -> None:
        super().__init__(message, status_code=status.HTTP_409_CONFLICT)


class BadRequestException(AppException):
    def __init__(self, message: str = "bad request") -> None:
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def handle_app_exception(
        request: Request, exc: AppException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(message=exc.message).model_dump(),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(message="internal server error").model_dump(),
        )
