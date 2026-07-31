from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import Agent
from app.modules.conversation.models import ModelUsageRecord
from app.modules.embed.models import PlatformEmbedClient
from app.modules.model_usage.schemas import (
    AgentUsageSummary,
    ClientUsageSummary,
    DayUsageSummary,
    ModelUsagePage,
    ModelUsageRecordRead,
    ModelUsageSummary,
    TokenUsageSummary,
)


class ModelUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _date_filters(
        *,
        platform_id: int,
        agent_id: int | None,
        client_id: str | None,
        start_date: date,
        end_date: date,
    ):
        start_at = datetime.combine(start_date, time.min)
        end_at = datetime.combine(end_date + timedelta(days=1), time.min)
        filters = [
            ModelUsageRecord.platform_id == platform_id,
            ModelUsageRecord.created_at >= start_at,
            ModelUsageRecord.created_at < end_at,
        ]
        if agent_id is not None:
            filters.append(ModelUsageRecord.agent_id == agent_id)
        if client_id is not None:
            filters.append(ModelUsageRecord.client_id == client_id)
        return filters

    @staticmethod
    def _page_count(total: int, page_size: int) -> int:
        return (total + page_size - 1) // page_size if total else 0

    async def list_records(
        self,
        *,
        platform_id: int,
        agent_id: int | None,
        client_id: str | None,
        start_date: date,
        end_date: date,
        page: int,
        page_size: int,
    ) -> ModelUsagePage:
        filters = self._date_filters(
            platform_id=platform_id,
            agent_id=agent_id,
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
        )
        base = (
            select(
                ModelUsageRecord,
                Agent.name.label("agent_name"),
                PlatformEmbedClient.name.label("client_name"),
            )
            .join(Agent, Agent.id == ModelUsageRecord.agent_id)
            .outerjoin(
                PlatformEmbedClient,
                (PlatformEmbedClient.platform_id == ModelUsageRecord.platform_id)
                & (PlatformEmbedClient.client_id == ModelUsageRecord.client_id),
            )
            .where(*filters)
        )
        total = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ModelUsageRecord)
                .where(*filters)
            )
            or 0
        )
        result = await self.session.execute(
            base.order_by(
                ModelUsageRecord.created_at.desc(),
                ModelUsageRecord.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [
            ModelUsageRecordRead.model_validate(
                {
                    **record.__dict__,
                    "agent_name": agent_name,
                    "client_name": client_name,
                }
            )
            for record, agent_name, client_name in result.all()
        ]
        return ModelUsagePage(
            page_no=page,
            page_size=page_size,
            items=items,
            total=total,
            pages=self._page_count(total, page_size),
        )

    async def summary(
        self,
        *,
        platform_id: int,
        agent_id: int | None,
        client_id: str | None,
        start_date: date,
        end_date: date,
    ) -> ModelUsageSummary:
        filters = self._date_filters(
            platform_id=platform_id,
            agent_id=agent_id,
            client_id=client_id,
            start_date=start_date,
            end_date=end_date,
        )
        metrics = (
            func.count(ModelUsageRecord.id).label("record_count"),
            func.coalesce(func.sum(ModelUsageRecord.prompt_tokens), 0).label(
                "prompt_tokens"
            ),
            func.coalesce(func.sum(ModelUsageRecord.completion_tokens), 0).label(
                "completion_tokens"
            ),
            func.coalesce(func.sum(ModelUsageRecord.total_tokens), 0).label(
                "total_tokens"
            ),
        )
        totals_row = await self.session.execute(
            select(*metrics).where(*filters)
        )
        totals = totals_row.one()

        agent_rows = await self.session.execute(
            select(
                ModelUsageRecord.agent_id,
                Agent.name,
                *metrics,
            )
            .join(Agent, Agent.id == ModelUsageRecord.agent_id)
            .where(*filters)
            .group_by(ModelUsageRecord.agent_id, Agent.name)
            .order_by(func.sum(ModelUsageRecord.total_tokens).desc())
        )
        by_agent = [
            AgentUsageSummary(
                agent_id=agent_id_value,
                agent_name=agent_name,
                record_count=record_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens_value,
            )
            for (
                agent_id_value,
                agent_name,
                record_count,
                prompt_tokens,
                completion_tokens,
                total_tokens_value,
            ) in agent_rows.all()
        ]

        client_rows = await self.session.execute(
            select(
                ModelUsageRecord.client_id,
                PlatformEmbedClient.name,
                *metrics,
            )
            .outerjoin(
                PlatformEmbedClient,
                (PlatformEmbedClient.platform_id == ModelUsageRecord.platform_id)
                & (PlatformEmbedClient.client_id == ModelUsageRecord.client_id),
            )
            .where(*filters)
            .group_by(ModelUsageRecord.client_id, PlatformEmbedClient.name)
            .order_by(func.sum(ModelUsageRecord.total_tokens).desc())
        )
        by_client = [
            ClientUsageSummary(
                client_id=client_id_value,
                client_name=client_name,
                record_count=record_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens_value,
            )
            for (
                client_id_value,
                client_name,
                record_count,
                prompt_tokens,
                completion_tokens,
                total_tokens_value,
            ) in client_rows.all()
        ]

        day_value = func.date(ModelUsageRecord.created_at).label("day")
        day_rows = await self.session.execute(
            select(day_value, *metrics)
            .where(*filters)
            .group_by(day_value)
            .order_by(day_value.asc())
        )
        by_day = [
            DayUsageSummary(
                day=(
                    day_value_result
                    if isinstance(day_value_result, date)
                    else date.fromisoformat(day_value_result)
                ),
                record_count=record_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens_value,
            )
            for (
                day_value_result,
                record_count,
                prompt_tokens,
                completion_tokens,
                total_tokens_value,
            ) in day_rows.all()
        ]
        return ModelUsageSummary(
            totals=TokenUsageSummary(
                record_count=totals.record_count,
                prompt_tokens=totals.prompt_tokens,
                completion_tokens=totals.completion_tokens,
                total_tokens=totals.total_tokens,
            ),
            by_agent=by_agent,
            by_client=by_client,
            by_day=by_day,
        )
