"""``scripts/tool_group_report.py``：动作序列还原与一次端到端回放（sqlite 内存库）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
    ConversationMessage,
)
from app.modules.platform.models import Platform
from app.modules.user.models import User
from app.shared.base_model import BaseModel
from scripts import tool_group_report


def _step(tool_name, metadata=None):
    return SimpleNamespace(tool_name=tool_name, step_metadata=metadata or {})


def test_step_actions_keeps_only_successful_group_loads():
    """只有带 ``tool_group`` 元数据的 load_tool_group 才是一次加载。

    失败的加载故意不写元数据（见 ``handle_loader_call``），否则重放会把一次
    「组名写错」的失败当成「已经加载过」。
    """

    actions = tool_group_report.step_actions(
        [
            _step("load_tool_group", {"tool_group": "ops"}),
            _step("load_tool_group", {"tool_group": None}),
            _step("order_query"),
            _step(None),
        ]
    )

    assert actions == [("load", "ops"), ("call", "order_query")]


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session) -> Conversation:
    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    user = User(name="Admin", email="admin@acme.dev", account="admin", password="x")
    session.add_all([agent, user])
    await session.flush()
    conversation = Conversation(
        platform_id=platform.id, agent_id=agent.id, user_id=user.id, title="回放"
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def _seed_run(session, conversation: Conversation) -> None:
    message = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content="帮我看下店铺今天的订单",
        status="completed",
    )
    session.add(message)
    await session.flush()
    run = AgentLoopRun(
        conversation_id=conversation.id,
        user_message_id=message.id,
        request_id="req-1",
        status="completed",
    )
    session.add(run)
    await session.flush()
    session.add_all(
        [
            AgentLoopStep(
                loop_run_id=run.id,
                sequence=1,
                step_type="builtin",
                title="调用工具：load_tool_group",
                status="succeeded",
                tool_name="load_tool_group",
                tool_call_id="call-1",
                step_metadata={"tool_group": "memory"},
            ),
            AgentLoopStep(
                loop_run_id=run.id,
                sequence=2,
                step_type="builtin",
                title="调用工具：memory_search",
                status="succeeded",
                tool_name="memory_search",
                tool_call_id="call-2",
            ),
            # 未加载即调用：线上会触发 activate_all 兜底，回放要能数出来
            AgentLoopStep(
                loop_run_id=run.id,
                sequence=3,
                step_type="builtin",
                title="调用工具：knowledge_search",
                status="failed",
                tool_name="knowledge_search",
                tool_call_id="call-3",
            ),
        ]
    )
    await session.flush()


def test_collect_stats_replays_single_run(monkeypatch):
    async def scenario():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                conversation = await _seed(session)
                await _seed_run(session, conversation)
                await session.commit()
                conversation_id = conversation.id
            monkeypatch.setattr(
                tool_group_report, "get_session_factory", lambda: session_factory
            )
            stats = await tool_group_report.collect_stats(
                limit=10, conversation_id=conversation_id
            )
        finally:
            await engine.dispose()
        return stats

    stats = asyncio.run(scenario())

    assert stats["runs"] == 1
    assert stats["tool_calls"] == 2
    assert stats["load_calls"] == 1
    assert stats["load_runs"] == 1
    # 用户消息命中 ops 关键词：预取一次
    assert stats["prefetch_runs"] == 1
    # knowledge_search 未加载即调用 → 一次兜底
    assert stats["fallback_runs"] == 1
    assert stats["avg_bound_chars_max"] > stats["avg_bound_chars_start"]
