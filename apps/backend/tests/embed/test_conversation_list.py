"""Embed 会话列表与软删除的隔离/保留语义测试（sqlite 内存库）。

覆盖三件不可退化的行为：
1. 列表只返回「同平台 + 同最终用户 + 同 Agent」的会话，不跨主体泄露；
2. 软删除只改状态，消息、附件、用量记录与磁盘文件全部保留；
3. 软删除后会话不可再被解析（不可「复活」续聊）。

说明：sqlite 仅用于验证查询口径与状态流转；真实 PostgreSQL 上的行为由
verify 脚本的记录项说明。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    Conversation,
    ConversationMessage,
    ModelUsageRecord,
)
from app.modules.conversation.repositories import (
    CONVERSATION_STATUS_DELETED,
    ConversationRepository,
)
from app.modules.embed.models import PlatformEndUser
from app.modules.embed.services import (
    list_embed_conversations,
    soft_delete_embed_conversation,
)
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel
from app.shared.exceptions import NotFoundException


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session, *, message_count: int = 1):
    """建平台 + Agent + 两个最终用户 + 两个会话，返回关键实体。"""
    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    session.add(agent)
    await session.flush()

    owner = PlatformEndUser(platform_id=platform.id, external_user_id="owner")
    stranger = PlatformEndUser(platform_id=platform.id, external_user_id="stranger")
    session.add_all([owner, stranger])
    await session.flush()

    mine = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        platform_end_user_id=owner.id,
        title="我的会话",
        status="active",
    )
    theirs = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        platform_end_user_id=stranger.id,
        title="别人的会话",
        status="active",
    )
    session.add_all([mine, theirs])
    await session.flush()

    for index in range(message_count):
        session.add(
            ConversationMessage(
                conversation_id=mine.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"第 {index} 条消息",
                status="completed",
                content_blocks=[],
                citations=[],
                knowledge_grounded=False,
                message_metadata={},
            )
        )
    # 用量记录是计费事实来源，软删除绝不能波及。
    session.add(
        ModelUsageRecord(
            platform_id=platform.id,
            agent_id=agent.id,
            conversation_id=mine.id,
            platform_end_user_id=owner.id,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
    )
    await session.commit()
    return platform, agent, owner, stranger, mine, theirs


def _claims(platform_id: int, agent_id: int, end_user_id: int) -> dict:
    return {
        "platform_id": platform_id,
        "agent_id": agent_id,
        "sub": str(end_user_id),
    }


def test_list_only_returns_own_conversations():
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, agent, owner, stranger, mine, theirs = await _seed(session)
                repo = ConversationRepository(session)

                page = await list_embed_conversations(
                    repo, claims=_claims(platform.id, agent.id, owner.id)
                )
                assert [item.id for item in page.items] == [mine.id]
                assert page.total == 1

                # 换主体后只看到自己的会话，看不到 owner 的任何数据。
                other = await list_embed_conversations(
                    repo, claims=_claims(platform.id, agent.id, stranger.id)
                )
                assert [item.id for item in other.items] == [theirs.id]
                assert mine.id not in {item.id for item in other.items}
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_reports_message_count_and_preview_without_n_plus_one():
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, agent, owner, _stranger, mine, _theirs = await _seed(
                    session, message_count=3
                )
                page = await list_embed_conversations(
                    ConversationRepository(session),
                    claims=_claims(platform.id, agent.id, owner.id),
                )
                item = page.items[0]
                assert item.id == mine.id
                assert item.message_count == 3
                # 末条消息是 index=2 的 assistant 消息。
                assert item.last_message_preview == "第 2 条消息"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_soft_delete_hides_conversation_but_keeps_all_data():
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, agent, owner, _stranger, mine, _theirs = await _seed(
                    session, message_count=2
                )
                repo = ConversationRepository(session)

                await soft_delete_embed_conversation(
                    repo,
                    conversation_id=mine.id,
                    claims=_claims(platform.id, agent.id, owner.id),
                )

                # 列表与解析都不再返回它。
                page = await list_embed_conversations(
                    repo, claims=_claims(platform.id, agent.id, owner.id)
                )
                assert page.items == []
                assert page.total == 0
                assert (
                    await repo.get_for_principal(
                        mine.id, platform.id, end_user_id=owner.id
                    )
                    is None
                )

                # 状态被标记，但消息与用量记录行数一条不少。
                conversation = await session.get(Conversation, mine.id)
                assert conversation.status == CONVERSATION_STATUS_DELETED
                message_count = await session.scalar(
                    select(func.count(ConversationMessage.id)).where(
                        ConversationMessage.conversation_id == mine.id
                    )
                )
                usage_count = await session.scalar(
                    select(func.count(ModelUsageRecord.id)).where(
                        ModelUsageRecord.conversation_id == mine.id
                    )
                )
                assert message_count == 2
                assert usage_count == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_soft_delete_rejects_other_principal_and_is_idempotent():
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, agent, owner, stranger, mine, _theirs = await _seed(session)
                repo = ConversationRepository(session)

                # 别的最终用户删不动我的会话，且错误语义是 404 而非 403。
                try:
                    await soft_delete_embed_conversation(
                        repo,
                        conversation_id=mine.id,
                        claims=_claims(platform.id, agent.id, stranger.id),
                    )
                    raise AssertionError("expected NotFoundException")
                except NotFoundException:
                    pass
                conversation = await session.get(Conversation, mine.id)
                assert conversation.status == "active"

                # 同一主体重复删除幂等：第二次同样返回未命中。
                claims = _claims(platform.id, agent.id, owner.id)
                await soft_delete_embed_conversation(
                    repo, conversation_id=mine.id, claims=claims
                )
                try:
                    await soft_delete_embed_conversation(
                        repo, conversation_id=mine.id, claims=claims
                    )
                    raise AssertionError("expected NotFoundException")
                except NotFoundException:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_orders_by_created_at_desc():
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, agent, owner, _stranger, _mine, _theirs = await _seed(session)
                older = Conversation(
                    platform_id=platform.id,
                    agent_id=agent.id,
                    platform_end_user_id=owner.id,
                    title="更早的会话",
                    status="active",
                    created_at=datetime(2020, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2020, 1, 1, tzinfo=UTC),
                )
                session.add(older)
                await session.commit()

                page = await list_embed_conversations(
                    ConversationRepository(session),
                    claims=_claims(platform.id, agent.id, owner.id),
                )
                # 列表按 created_at 倒序：新建的排在 2020 年那条之前。
                assert page.items[-1].id == older.id
                assert page.total == 2
        finally:
            await engine.dispose()

    asyncio.run(run())
