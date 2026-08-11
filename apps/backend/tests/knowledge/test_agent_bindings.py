"""智能体知识库关联仓储测试。"""
import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.knowledge.repositories import KnowledgeRepository
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


def test_agent_bindings_are_isolated_and_unbind_is_idempotent():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            other_platform = Platform(name="Other", code="other")
            session.add_all([platform, other_platform])
            await session.flush()
            agent = Agent(platform_id=platform.id, name="客服", slug="support")
            session.add(agent)
            await session.flush()
            base = KnowledgeBase(
                platform_id=platform.id,
                name="产品手册",
                slug="manual",
                embedding_model="text-embedding-3-small",
                embedding_dimension=1536,
            )
            other_base = KnowledgeBase(
                platform_id=other_platform.id,
                name="其他平台资料",
                slug="other",
                embedding_model="text-embedding-3-small",
                embedding_dimension=1536,
            )
            session.add_all([base, other_base])
            await session.flush()
            session.add(
                KnowledgeDocument(
                    knowledge_base_id=base.id,
                    source_type="file",
                    title="手册.pdf",
                    status="ready",
                )
            )
            await session.commit()

            repo = KnowledgeRepository(session)
            await repo.bind_to_agent(agent.id, base.id, platform.id, 0)
            await repo.bind_to_agent(agent.id, other_base.id, platform.id, 0)

            rows = await repo.list_agent_bindings(platform.id, agent.id)
            assert len(rows) == 1
            assert rows[0]["knowledge_base_id"] == base.id
            assert rows[0]["name"] == "产品手册"
            assert rows[0]["document_count"] == 1
            assert rows[0]["has_embedding_api_key"] is False

            assert await repo.unbind_agent(agent.id, base.id, platform.id) is True
            assert await repo.unbind_agent(agent.id, base.id, platform.id) is False
            assert (
                await repo.unbind_agent(agent.id, other_base.id, platform.id)
                is False
            )

        await engine.dispose()

    asyncio.run(run())
