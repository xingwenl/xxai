from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    message: str
    data: T | None = None
    meta: ResponseMeta | None = None
    code: int


def success_response(
    data: Any = None,
    message: str = "ok",
    meta: ResponseMeta | None = None,
) -> ApiResponse[Any]:
    return ApiResponse(success=True, message=message, data=data, meta=meta, code=0)


def error_response(
    message: str,
    code: int = 500,
    data: Any = None,
    meta: ResponseMeta | None = None,
) -> ApiResponse[Any]:
    return ApiResponse(success=False, message=message, data=data, meta=meta, code=code)
