import asyncio

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    Conversation,
    ConversationMessage,
    ModelUsageRecord,
)
from app.modules.conversation.repositories import ConversationRepository
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


def test_repository_persists_model_usage_detail_record():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        async with engine.begin() as connection:
            await connection.run_sync(BaseModel.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            session.add(platform)
            await session.flush()
            agent = Agent(platform_id=platform.id, name="Support", slug="support")
            end_user = PlatformEndUser(
                platform_id=platform.id,
                external_user_id="external_1",
            )
            session.add_all([agent, end_user])
            await session.flush()
            conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                platform_end_user_id=end_user.id,
                title="你好",
            )
            session.add(conversation)
            await session.flush()
            message = ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content="回答",
            )
            session.add(message)
            await session.commit()

            await ConversationRepository(session).record_model_usage(
                platform_id=platform.id,
                agent_id=agent.id,
                agent_version_id=None,
                client_id="client_live",
                platform_end_user_id=end_user.id,
                conversation_id=conversation.id,
                message_id=message.id,
                request_id="req-usage",
                model_name="deepseek-v4-pro",
                prompt_tokens=12,
                completion_tokens=5,
                total_tokens=17,
            )

            record = await session.scalar(select(ModelUsageRecord))
            assert record is not None
            assert record.client_id == "client_live"
            assert record.platform_end_user_id == end_user.id
            assert record.prompt_tokens == 12
            assert record.completion_tokens == 5
            assert record.total_tokens == 17

        await engine.dispose()

    asyncio.run(run())
