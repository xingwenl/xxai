from __future__ import annotations

from math import ceil
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


def build_pagination_meta(params: PaginationParams, total: int) -> PaginationMeta:
    return PaginationMeta(
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=max(1, ceil(total / params.page_size)) if total else 1,
    )


class PageData(BaseModel, Generic[T]):
    page_no: int
    page_size: int
    items: list[T]
    total: int
    pages: int


def build_page_data(items: list[T], params: PaginationParams, total: int) -> PageData[T]:
    meta = build_pagination_meta(params, total)
    return PageData(
        page_no=meta.page,
        page_size=meta.page_size,
        items=items,
        total=meta.total,
        pages=meta.total_pages,
    )


class PageResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "操作成功"
    data: T


def pagination_dependency(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)
