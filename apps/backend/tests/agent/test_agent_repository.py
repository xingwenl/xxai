"""智能体详情仓储测试。"""
import asyncio
from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.agent.repositories import AgentRepository
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_get_agent_detail_loads_current_version_and_isolates_platform():
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
            session.add_all([agent, other_agent])
            await session.flush()
            version = AgentVersion(
                agent_id=agent.id,
                version=1,
                system_prompt="你是客服助手",
                model_name="gpt-4o-mini",
                temperature=0.2,
                created_at=datetime.now(UTC),
                published_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            agent.default_version_id = version.id
            await session.commit()

            repo = AgentRepository(session)
            detail = await repo.get_agent_detail(agent.id, platform.id)
            assert detail is not None
            assert detail.default_version_id == version.id
            assert detail.default_version is not None
            assert detail.default_version.model_name == "gpt-4o-mini"

            assert await repo.get_agent_detail(agent.id, other_platform.id) is None

        await engine.dispose()

    asyncio.run(run())
