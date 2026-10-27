"""工具组加载态重放的仓储测试（sqlite 内存库）。

加载态不落库，靠 ``agent_loop_steps.step_metadata`` 里 ``tool_group`` 这个键
重放（见 ``ToolGroupState.restore``）。这里钉住三件事：只认 load_tool_group
这一步、元数据缺失/非字符串要能跳过、续跑时可以排除「本次运行自己的步骤」。
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
)
from app.modules.conversation.repositories import ConversationRepository
from app.modules.platform.models import Platform
from app.modules.user.models import User
from app.shared.base_model import BaseModel


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_conversation(session) -> Conversation:
    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    user = User(name="Admin", email="admin@acme.dev", account="admin", password="x")
    session.add_all([agent, user])
    await session.flush()
    conversation = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        user_id=user.id,
        title="多轮",
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def _add_step(
    session,
    *,
    conversation_id: int,
    request_id: str,
    tool_name: str | None,
    step_metadata: dict | None,
    sequence: int = 1,
) -> AgentLoopRun:
    loop = AgentLoopRun(
        conversation_id=conversation_id, request_id=request_id, status="completed"
    )
    session.add(loop)
    await session.flush()
    session.add(
        AgentLoopStep(
            loop_run_id=loop.id,
            sequence=sequence,
            step_type="tool_call",
            title="调用工具",
            status="completed",
            tool_name=tool_name,
            step_metadata=step_metadata or {},
        )
    )
    await session.flush()
    return loop


def test_replays_loaded_groups_from_step_metadata() -> None:
    """历史里加载过的组被读回；非 load_tool_group 步骤与坏数据被忽略。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                conversation = await _seed_conversation(session)
                await _add_step(
                    session,
                    conversation_id=conversation.id,
                    request_id="req-1",
                    tool_name="load_tool_group",
                    step_metadata={"tool_group": "ops"},
                    sequence=1,
                )
                await _add_step(
                    session,
                    conversation_id=conversation.id,
                    request_id="req-1",
                    tool_name="load_tool_group",
                    step_metadata={"tool_group": "memory"},
                    sequence=2,
                )
                # 非加载工具步骤：即便 metadata 里恰好有同名键也不应计入。
                await _add_step(
                    session,
                    conversation_id=conversation.id,
                    request_id="req-1",
                    tool_name="memory_search",
                    step_metadata={"tool_group": "content"},
                    sequence=3,
                )
                # 兜底（全量激活）与异常元数据：跳过而不是抛错。
                await _add_step(
                    session,
                    conversation_id=conversation.id,
                    request_id="req-1",
                    tool_name="load_tool_group",
                    step_metadata=None,
                    sequence=4,
                )
                await _add_step(
                    session,
                    conversation_id=conversation.id,
                    request_id="req-1",
                    tool_name="load_tool_group",
                    step_metadata={"tool_group": 3},
                    sequence=5,
                )
                await session.commit()

                repo = ConversationRepository(session)
                assert await repo.list_loaded_tool_groups(conversation.id) == {
                    "ops",
                    "memory",
                }
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_excludes_current_loop_when_resuming() -> None:
    """续跑只恢复「本次运行开始之前」的组，本运行中途加载的丢弃。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                conversation = await _seed_conversation(session)
                await _add_step(
                    session,
                    conversation_id=conversation.id,
                    request_id="req-1",
                    tool_name="load_tool_group",
                    step_metadata={"tool_group": "ops"},
                )
                current = await _add_step(
                    session,
                    conversation_id=conversation.id,
                    request_id="req-2",
                    tool_name="load_tool_group",
                    step_metadata={"tool_group": "memory"},
                )
                await session.commit()

                repo = ConversationRepository(session)
                assert await repo.list_loaded_tool_groups(
                    conversation.id, exclude_loop_run_id=current.id
                ) == {"ops"}
                # 不排除时两组都在：这是「多轮对话」而非「续跑」的口径。
                assert await repo.list_loaded_tool_groups(conversation.id) == {
                    "ops",
                    "memory",
                }
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())
