"""get_runtime_info 业务工具单测：注册契约、白名单返回结构与降级。"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.conversation.models import Conversation, ModelUsageRecord
from app.modules.embed.models import PlatformEmbedClient, PlatformEndUser
from app.modules.platform.models import Platform
from app.modules.tools.business.framework import BusinessToolContext
from app.modules.tools.business.registry import get_business_tool
from app.shared.base_model import BaseModel


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _ctx(session, **kwargs) -> BusinessToolContext:
    values = dict(
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        session=session,
    )
    values.update(kwargs)
    return BusinessToolContext(**values)


def test_registered_with_empty_input_schema():
    tool = get_business_tool("get_runtime_info")
    assert tool is not None
    assert tool.name == "get_runtime_info"
    assert "模型" in tool.description
    assert "token" in tool.description
    assert tool.input_schema == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_returns_model_version_usage_and_client_identity():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            session.add(platform)
            await session.flush()
            agent = Agent(platform_id=platform.id, name="客服", slug="support")
            session.add(agent)
            await session.flush()
            version = AgentVersion(
                agent_id=agent.id,
                version=3,
                system_prompt="base",
                model_name="gpt-5.2",
                temperature=0.2,
                model_options={},
                capabilities={
                    "image": True,
                    "native_file": False,
                    "text_retrieval": True,
                },
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            )
            session.add(version)
            await session.flush()
            agent.default_version_id = version.id
            await session.flush()
            end_user = PlatformEndUser(
                platform_id=platform.id, external_user_id="external-1"
            )
            client = PlatformEmbedClient(
                platform_id=platform.id,
                client_id="client_live",
                name="线上站点",
                secret_hash="hash",
                allowed_origins=["https://example.test"],
            )
            session.add_all([end_user, client])
            await session.flush()
            conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                platform_end_user_id=end_user.id,
                title="会话",
            )
            session.add(conversation)
            await session.flush()
            session.add(
                ModelUsageRecord(
                    platform_id=platform.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                    client_id=client.client_id,
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                )
            )
            await session.commit()

            tool = get_business_tool("get_runtime_info")
            result = await tool.handler(
                {},
                _ctx(
                    session,
                    platform_id=platform.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                ),
            )

            assert result["model"]["name"] == "gpt-5.2"
            assert result["model"]["temperature"] == 0.2
            assert result["model"]["capabilities"] == {
                "image": True,
                "text_retrieval": True,
            }
            assert result["agent"]["agentId"] == agent.id
            assert result["agent"]["name"] == "客服"
            assert result["version"]["agentVersion"] == 3
            assert result["version"]["serviceVersion"]
            assert result["usage"]["conversation"]["promptTokens"] == 10
            assert result["usage"]["conversation"]["completionTokens"] == 5
            assert result["usage"]["conversation"]["totalTokens"] == 15
            assert result["usage"]["conversation"]["messageCount"] == 1
            assert result["usage"]["today"]["totalTokens"] == 15
            assert result["usage"]["total"]["totalTokens"] == 15
            assert result["client"]["clientId"] == "client_live"
            assert result["client"]["name"] == "线上站点"
            # 白名单：绝不返回密钥或 base_url
            assert "api_key" not in result
            assert "base_url" not in result

        await engine.dispose()

    asyncio.run(run())


def test_degrades_to_null_when_agent_missing():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            session.add(platform)
            await session.commit()

            tool = get_business_tool("get_runtime_info")
            result = await tool.handler(
                {},
                _ctx(session, platform_id=platform.id, agent_id=999, conversation_id=1),
            )

            assert result["model"] is None
            assert result["agent"] is None
            assert result["version"] is None
            assert result["usage"]["conversation"] is not None
            assert result["usage"]["conversation"]["totalTokens"] == 0
            assert result["client"] is None

        await engine.dispose()

    asyncio.run(run())
