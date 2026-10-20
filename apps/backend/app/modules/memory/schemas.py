from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryKind = Literal["fact", "event"]
MemorySource = Literal["explicit", "inferred"]


class MemoryCreate(BaseModel):
    kind: MemoryKind = Field(description="记忆类别：fact=事实，event=经历")
    key: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        description="事实的稳定标识；kind=fact 时必填，kind=event 时忽略",
    )
    content: str = Field(min_length=1, max_length=2000, description="记忆正文")
    occurred_at: datetime | None = Field(
        default=None,
        description="事实的生效起点或经历的发生时间；经历不传则取当前时间",
    )


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    occurred_at: datetime | None = None


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    kind: MemoryKind
    key: str | None
    content: str
    occurred_at: datetime | None
    valid_until: datetime | None
    source: MemorySource
    source_conversation_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MemoryListData(BaseModel):
    items: list[MemoryRead]
    total: int
    fact_count: int
    event_count: int


def memory_read(row) -> MemoryRead:
    """把 ORM 行转成出参：``is_active`` 由 ``valid_until`` 派生，不单独存列。"""

    return MemoryRead(
        id=row.id,
        platform_id=row.platform_id,
        kind=row.kind,
        key=row.key,
        content=row.content,
        occurred_at=row.occurred_at,
        valid_until=row.valid_until,
        source=row.source,
        source_conversation_id=row.source_conversation_id,
        is_active=row.valid_until is None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
