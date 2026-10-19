"""微信助手绑定仓库单元测试（sqlite 内存库）。"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.agent.models import AgentVersion
from app.modules.platform.models import Platform
from app.modules.user.models import User
from app.modules.wechat_bot.repositories import WeChatBotBindingRepository
from app.shared.base_model import BaseModel


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_binding_repository_crud_and_lookup():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            user = User(
                name="Admin",
                email="admin@acme.dev",
                account="admin",
                password="x",
            )
            session.add_all([platform, user])
            await session.flush()

            repo = WeChatBotBindingRepository(session)
            binding = await repo.create(
                platform_id=platform.id,
                user_id=user.id,
                status="active",
                bot_token_encrypted="enc-token",
                api_token_hash="abc123",
                api_token_encrypted="enc-api-token",
                ilink_bot_id="bot-1",
                ilink_user_id="wx-1",
                is_active=True,
            )

            assert (
                await repo.get_for_user(binding.id, platform.id, user.id) is not None
            )
            assert await repo.get_for_user(binding.id, platform.id, user.id + 999) is None
            assert (
                await repo.get_by_api_token_hash("abc123") is not None
            )
            assert await repo.get_by_api_token_hash("nope") is None
            assert len(await repo.list_active()) == 1
            assert len(await repo.list_for_user(platform.id, user.id)) == 1

            await repo.update(binding, is_active=False, status="disabled")
            assert await repo.get_by_api_token_hash("abc123") is None

        await engine.dispose()

    asyncio.run(run())


def test_binding_repository_default_agent_lookup():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            session.add(platform)
            await session.flush()
            agent = Agent(
                platform_id=platform.id,
                name="默认",
                slug="default",
                is_default=True,
            )
            session.add(agent)
            await session.flush()
            version = AgentVersion(
                agent_id=agent.id,
                version=1,
                system_prompt="你是默认助手",
                temperature=0.2,
                created_at=datetime.now(UTC),
                published_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            agent.default_version_id = version.id
            await session.commit()

            from app.modules.agent.repositories import AgentRepository

            default = await AgentRepository(session).get_default_agent(platform.id)
            assert default is not None and default.id == agent.id

        await engine.dispose()

    asyncio.run(run())
