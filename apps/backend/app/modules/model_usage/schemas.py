from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ModelUsageRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    agent_id: int
    agent_name: str
    client_id: str | None = None
    client_name: str | None = None
    platform_end_user_id: int | None = None
    conversation_id: int
    request_id: str | None = None
    model_name: str | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ModelUsagePage(BaseModel):
    page_no: int
    page_size: int
    items: list[ModelUsageRecordRead]
    total: int
    pages: int


class TokenUsageSummary(BaseModel):
    record_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AgentUsageSummary(TokenUsageSummary):
    agent_id: int
    agent_name: str


class ClientUsageSummary(TokenUsageSummary):
    client_id: str | None = None
    client_name: str | None = None


class DayUsageSummary(TokenUsageSummary):
    day: date


class ModelUsageSummary(BaseModel):
    totals: TokenUsageSummary
    by_agent: list[AgentUsageSummary]
    by_client: list[ClientUsageSummary]
    by_day: list[DayUsageSummary]


class ModelUsageQuery(BaseModel):
    agent_id: int | None = None
    client_id: str | None = None
    start_date: date
    end_date: date
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
