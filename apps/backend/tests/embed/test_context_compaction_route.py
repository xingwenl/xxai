"""手动压缩 REST 服务的入口语义测试（sqlite 内存库 + 真实仓储）。

``POST /embed/conversations/{id}/context/compact`` 的隔离语义必须和相邻 embed
接口一字不差：非本主体按不存在处理（404，不泄露存在性）；Agent 已下架/无版本时
也不凭空造模型客户端。成功路径则跑真实的 ``compact_conversation``，验证 REST
投影是 snake_case 且带上了窗口与百分比。
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.modules.agent.models import Agent, AgentVersion
from app.modules.conversation.models import (
    Conversation,
    ConversationContextCompaction,
    ConversationMessage,
)
from app.modules.conversation.repositories import ConversationRepository
from app.modules.embed.models import PlatformEndUser
from app.modules.embed.services import compact_embed_conversation
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel
from app.shared.exceptions import NotFoundException


class _FakeSummaryModel:
    model_name = "fake-summary-model"

    def __init__(self, text: str = "摘要正文"):
        self.text = text
        self.prompts: list[list] = []

    def bind(self, **_kwargs):
        return self

    async def ainvoke(self, messages):
        self.prompts.append(list(messages))
        return SimpleNamespace(
            content=self.text,
            response_metadata={"finish_reason": "stop"},
            usage_metadata=None,
        )


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session, *, message_count: int = 8, published: bool = True):
    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot", is_active=True)
    end_user = PlatformEndUser(
        platform_id=platform.id, external_user_id="external_1", is_active=True
    )
    session.add_all([agent, end_user])
    await session.flush()

    if published:
        version = AgentVersion(
            agent_id=agent.id,
            version=1,
            system_prompt="你是助手",
            created_at=datetime.now(UTC),
            published_at=datetime.now(UTC),
            # 显式窗口：这样手动压缩不必依赖模型名映射就能给出百分比。
            context_window_tokens=1_000,
        )
        session.add(version)
        await session.flush()
        agent.default_version_id = version.id

    conversation = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        platform_end_user_id=end_user.id,
        title="手动压缩",
    )
    session.add(conversation)
    await session.flush()
    for index in range(message_count):
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"第 {index + 1} 轮" + "填充" * 20,
                status="completed",
                created_at=datetime.now(UTC),
            )
        )
    await session.commit()
    return platform, agent, end_user, conversation


def _patch_model(monkeypatch, model):
    """只替换模型解析面：仓储、压缩、落库全部走真实实现。"""

    async def fake_resolve_chat_model(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.modules.model_registry.resolver.resolve_chat_model",
        fake_resolve_chat_model,
    )
    monkeypatch.setattr(
        "app.modules.agent.services.build_chat_model",
        lambda *_args, **_kwargs: model,
    )


@pytest.fixture(autouse=True)
def _small_keep_recent():
    saved = {
        key: os.environ.get(key)
        for key in (
            "CONTEXT_COMPACTION_KEEP_RECENT_TOKENS",
            "CONTEXT_COMPACTION_RESERVE_TOKENS",
        )
    }
    os.environ["CONTEXT_COMPACTION_KEEP_RECENT_TOKENS"] = "40"
    os.environ["CONTEXT_COMPACTION_RESERVE_TOKENS"] = "1024"
    get_settings.cache_clear()
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()


def test_compact_returns_snake_case_projection_and_writes_row(monkeypatch):
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, _agent, end_user, conversation = await _seed(session)
                model = _FakeSummaryModel("压缩后的摘要")
                _patch_model(monkeypatch, model)
                repo = ConversationRepository(session)
                claims = {"platform_id": platform.id, "sub": str(end_user.id)}

                result = await compact_embed_conversation(
                    repo,
                    session=session,
                    conversation_id=conversation.id,
                    claims=claims,
                    instructions="重点保留接口约定",
                )

                assert set(result) == {
                    "compacted",
                    "reason",
                    "trigger",
                    "tokens_before",
                    "tokens_after",
                    "window_tokens",
                    "used_tokens",
                    "percent",
                }
                assert result["compacted"] is True
                assert result["trigger"] == "manual"
                assert result["window_tokens"] == 1_000
                assert result["tokens_before"] > result["tokens_after"]
                assert 0 < result["percent"] < 100
                assert "重点保留接口约定" in "\n".join(
                    str(message.content) for message in model.prompts[-1]
                )

                stored = await session.scalar(select(ConversationContextCompaction))
                assert stored is not None
                assert stored.trigger == "manual"
                assert stored.instructions == "重点保留接口约定"
                assert stored.first_kept_message_id is not None

                # 幂等：重复点「压缩」不报错也不写第二行。
                again = await compact_embed_conversation(
                    repo,
                    session=session,
                    conversation_id=conversation.id,
                    claims=claims,
                )
                assert again["compacted"] is False
                assert again["reason"] == "nothing_to_compact"
                rows = (
                    await session.scalars(select(ConversationContextCompaction))
                ).all()
                assert len(rows) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_compact_hides_conversations_of_other_end_users(monkeypatch):
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, _agent, _end_user, conversation = await _seed(session)
                _patch_model(monkeypatch, _FakeSummaryModel())
                repo = ConversationRepository(session)

                with pytest.raises(NotFoundException):
                    await compact_embed_conversation(
                        repo,
                        session=session,
                        conversation_id=conversation.id,
                        claims={"platform_id": platform.id, "sub": "999999"},
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_compact_rejects_agent_without_published_version(monkeypatch):
    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                platform, _agent, end_user, conversation = await _seed(
                    session, published=False
                )
                _patch_model(monkeypatch, _FakeSummaryModel())
                repo = ConversationRepository(session)

                with pytest.raises(NotFoundException):
                    await compact_embed_conversation(
                        repo,
                        session=session,
                        conversation_id=conversation.id,
                        claims={"platform_id": platform.id, "sub": str(end_user.id)},
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())
