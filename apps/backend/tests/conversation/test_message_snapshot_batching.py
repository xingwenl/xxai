"""消息时间线的批量读取：数据库往返次数不随 Loop 数量增长。

`build_message_snapshots` 原先逐 Loop 读取步骤与委派子运行，打开一次长会话的
时间线会产生 O(轮数) 次查询。这里用 SQL 计数把「往返次数恒定」钉成回归口径，
并校验批量路径与逐条路径拼出的投影逐字段一致。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
    ConversationMessage,
    ModelUsageRecord,
)
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.serializers import build_message_snapshots
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


async def _make_session():
    """建内存 sqlite 与会话工厂，同时记录所有实际下发的 SQL。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def record_statement(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False), statements


async def _add_message(session, conversation_id: int, role: str, content: str):
    message = ConversationMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        status="completed",
        content_blocks=[],
        citations=[],
        knowledge_grounded=False,
        message_metadata={},
    )
    session.add(message)
    await session.flush()
    return message


async def _seed(session, *, loop_count: int, delegated_per_loop: int) -> int:
    """建一段会话：每条 Loop 挂 2 个步骤，按需再挂若干委派子运行与用量记录。"""
    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="客服机器人", slug="support")
    session.add(agent)
    await session.flush()
    end_user = PlatformEndUser(platform_id=platform.id, external_user_id="ext-1")
    session.add(end_user)
    await session.flush()
    conversation = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        platform_end_user_id=end_user.id,
        title="时间线",
        status="active",
    )
    session.add(conversation)
    await session.flush()

    for index in range(loop_count):
        user_message = await _add_message(
            session, conversation.id, "user", f"第 {index} 问"
        )
        assistant_message = await _add_message(
            session, conversation.id, "assistant", f"第 {index} 答"
        )
        loop = AgentLoopRun(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            request_id=f"req-{index}",
            status="completed",
            summary=f"摘要 {index}",
            run_metadata={},
        )
        session.add(loop)
        await session.flush()
        for sequence in range(2):
            session.add(
                AgentLoopStep(
                    loop_run_id=loop.id,
                    sequence=sequence,
                    step_type="tool",
                    title=f"步骤 {index}-{sequence}",
                    status="completed",
                    citation_refs=[],
                    step_metadata={},
                )
            )
        for delegated_index in range(delegated_per_loop):
            child_conversation = Conversation(
                platform_id=platform.id,
                agent_id=agent.id,
                platform_end_user_id=end_user.id,
                title="子会话",
                status="active",
            )
            session.add(child_conversation)
            await session.flush()
            child_loop = AgentLoopRun(
                conversation_id=child_conversation.id,
                request_id=f"child-{index}-{delegated_index}",
                status="completed",
                summary="子摘要",
                parent_loop_run_id=loop.id,
                run_metadata={"delegationMode": "self"},
            )
            session.add(child_loop)
            await session.flush()
            session.add(
                ModelUsageRecord(
                    platform_id=platform.id,
                    agent_id=agent.id,
                    conversation_id=child_conversation.id,
                    prompt_tokens=3,
                    completion_tokens=4,
                    total_tokens=7,
                )
            )
    await session.flush()
    return conversation.id


async def _snapshot_with_statement_count(session, conversation_id: int, statements):
    """清空计数后跑一次快照构建，返回 (投影, 本次下发的 SQL 列表)。"""
    repo = ConversationRepository(session)
    messages = await repo.list_messages(conversation_id)
    statements.clear()
    payload = await build_message_snapshots(
        repo, conversation_id=conversation_id, messages=messages
    )
    return payload, list(statements)


class _PerLoopRepo:
    """只暴露批量改造前方法的仓储替身：验证兼容分支与原路径逐字段一致。"""

    def __init__(self, repo):
        self._repo = repo

    async def list_loops(self, conversation_id: int):
        return await self._repo.list_loops(conversation_id)

    async def list_loop_steps(self, loop_run_id: int):
        return await self._repo.list_loop_steps(loop_run_id)

    async def list_child_loops(self, parent_loop_run_id: int):
        return await self._repo.list_child_loops(parent_loop_run_id)

    async def usage_by_conversation_ids(self, conversation_ids: list[int]):
        return await self._repo.usage_by_conversation_ids(conversation_ids)


def test_snapshot_query_count_is_constant():
    """2 轮与 8 轮的会话，构建一次时间线投影的 SQL 条数必须相同。"""

    async def run():
        counts: list[int] = []
        # 每个规模单独一个内存库：platforms.code 唯一约束不允许同库重复种子。
        for loop_count in (2, 8):
            engine, session_factory, statements = await _make_session()
            try:
                async with session_factory() as session:
                    conversation_id = await _seed(
                        session, loop_count=loop_count, delegated_per_loop=1
                    )
                    await session.commit()
                    _payload, executed = await _snapshot_with_statement_count(
                        session, conversation_id, statements
                    )
                    # 恒定 4 次：Loop 列表、步骤、子运行、子运行用量各一次。
                    assert len(executed) == 4, executed
                    counts.append(len(executed))
            finally:
                await engine.dispose()

        assert counts[0] == counts[1]

    asyncio.run(run())


def test_batched_snapshot_matches_per_loop_projection():
    """批量路径必须与逐条路径逐字段一致，且委派用量/模式不丢。"""

    async def run():
        engine, session_factory, statements = await _make_session()
        try:
            async with session_factory() as session:
                conversation_id = await _seed(
                    session, loop_count=3, delegated_per_loop=1
                )
                await session.commit()
                repo = ConversationRepository(session)
                messages = await repo.list_messages(conversation_id)

                batched = await build_message_snapshots(
                    repo, conversation_id=conversation_id, messages=messages
                )
                fallback = await build_message_snapshots(
                    _PerLoopRepo(repo),
                    conversation_id=conversation_id,
                    messages=messages,
                )
                assert batched == fallback

                assistant_snapshots = [
                    item for item in batched if item["role"] == "assistant"
                ]
                assert len(assistant_snapshots) == 3
                for index, snapshot in enumerate(assistant_snapshots):
                    loop = snapshot["loop"]
                    assert loop["requestId"] == f"req-{index}"
                    assert [step["title"] for step in loop["steps"]] == [
                        f"步骤 {index}-0",
                        f"步骤 {index}-1",
                    ]
                    delegated = loop["delegatedRuns"][0]
                    assert delegated["mode"] == "self"
                    assert delegated["usage"]["totalTokens"] == 7
                assert assistant_snapshots[0]["loop"]["id"].isdigit()
        finally:
            await engine.dispose()

    asyncio.run(run())
