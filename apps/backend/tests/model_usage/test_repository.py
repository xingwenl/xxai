import asyncio
from datetime import UTC, date, datetime

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.conversation.models import Conversation, ModelUsageRecord
from app.modules.embed.models import PlatformEmbedClient, PlatformEndUser
from app.modules.model_usage.repositories import ModelUsageRepository
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


def _usage(
    *,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    created_at: datetime,
    client_id: str | None,
    platform_end_user_id: int | None,
    total_tokens: int,
) -> ModelUsageRecord:
    return ModelUsageRecord(
        platform_id=platform_id,
        agent_id=agent_id,
        client_id=client_id,
        platform_end_user_id=platform_end_user_id,
        conversation_id=conversation_id,
        created_at=created_at,
        updated_at=created_at,
        prompt_tokens=total_tokens - 5,
        completion_tokens=5,
        total_tokens=total_tokens,
    )


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_usage_repository_lists_and_summarizes_by_agent_client_and_day():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            other_platform = Platform(name="Other", code="other")
            session.add_all([platform, other_platform])
            await session.flush()

            agent = Agent(platform_id=platform.id, name="客服", slug="support")
            other_agent = Agent(
                platform_id=other_platform.id, name="Other", slug="other"
            )
            client = PlatformEmbedClient(
                platform_id=platform.id,
                client_id="client_live",
                name="线上站点",
                secret_hash="hash",
                allowed_origins=["https://example.test"],
            )
            end_user = PlatformEndUser(
                platform_id=platform.id,
                external_user_id="external-1",
            )
            session.add_all([agent, other_agent, client, end_user])
            await session.flush()
            conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                platform_end_user_id=end_user.id,
                title="测试",
            )
            session.add(conversation)
            await session.flush()
            session.add(
                _usage(
                    platform_id=platform.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                    created_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
                    client_id=client.client_id,
                    platform_end_user_id=end_user.id,
                    total_tokens=17,
                )
            )
            session.add(
                _usage(
                    platform_id=platform.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                    created_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
                    client_id=client.client_id,
                    platform_end_user_id=end_user.id,
                    total_tokens=20,
                )
            )
            await session.commit()

            repository = ModelUsageRepository(session)
            page = await repository.list_records(
                platform_id=platform.id,
                agent_id=None,
                client_id=None,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
                page=1,
                page_size=20,
            )
            summary = await repository.summary(
                platform_id=platform.id,
                agent_id=None,
                client_id=None,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
            )

            assert page.total == 2
            assert page.items[0].client_name == "线上站点"
            assert summary.totals.total_tokens == 37
            assert summary.by_agent[0].agent_id == agent.id
            assert summary.by_client[0].client_id == "client_live"
            assert [item.day for item in summary.by_day] == [
                date(2026, 7, 1),
                date(2026, 7, 2),
            ]
            assert [item.total_tokens for item in summary.by_day] == [17, 20]

        await engine.dispose()

    asyncio.run(run())


def test_usage_repository_uses_inclusive_end_date_and_returns_empty_summary():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            session.add(platform)
            await session.flush()
            agent = Agent(platform_id=platform.id, name="客服", slug="support")
            end_user = PlatformEndUser(
                platform_id=platform.id, external_user_id="external-1"
            )
            session.add_all([agent, end_user])
            await session.flush()
            conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                platform_end_user_id=end_user.id,
                title="测试",
            )
            session.add(conversation)
            await session.flush()
            session.add(
                _usage(
                    platform_id=platform.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                    created_at=datetime(2026, 7, 2, 23, 59, tzinfo=UTC),
                    client_id=None,
                    platform_end_user_id=end_user.id,
                    total_tokens=10,
                )
            )
            await session.commit()

            repository = ModelUsageRepository(session)
            summary = await repository.summary(
                platform_id=platform.id,
                agent_id=None,
                client_id=None,
                start_date=date(2026, 7, 2),
                end_date=date(2026, 7, 2),
            )
            empty = await repository.summary(
                platform_id=platform.id,
                agent_id=None,
                client_id=None,
                start_date=date(2026, 7, 3),
                end_date=date(2026, 7, 3),
            )

            assert summary.totals.total_tokens == 10
            assert empty.totals.total_tokens == 0
            assert empty.by_agent == []
            assert empty.by_client == []
            assert empty.by_day == []

        await engine.dispose()

    asyncio.run(run())
