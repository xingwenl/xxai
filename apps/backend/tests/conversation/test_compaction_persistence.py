"""压缩落库行为的真库测试（SQLite 内存库 + 伪造模型）。

覆盖 spec 验收标准里三条落库约束：
1. 摘要成功才写压缩行，且 ``first_kept_message_id`` 指向保留区首行；
2. 摘要失败/被长度截断时**放弃本次压缩、不写坏 checkpoint**，调用方得到
   ``summary_failed``；
3. 第二次压缩把旧摘要并入新摘要（``<previous-summary>``），旧行保留作审计。
"""

import asyncio
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.modules.agent.models import Agent
from app.modules.conversation.compaction import compact_conversation
from app.modules.conversation.models import (
    Conversation,
    ConversationContextCompaction,
    ConversationMessage,
)
from app.modules.conversation.repositories import ConversationRepository
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


@contextmanager
def _small_keep_recent():
    """把保留量压到几十 token，让几句短消息也能触发压缩。"""

    saved = {
        "CONTEXT_COMPACTION_KEEP_RECENT_TOKENS": os.environ.get(
            "CONTEXT_COMPACTION_KEEP_RECENT_TOKENS"
        ),
        "CONTEXT_COMPACTION_RESERVE_TOKENS": os.environ.get(
            "CONTEXT_COMPACTION_RESERVE_TOKENS"
        ),
    }
    os.environ["CONTEXT_COMPACTION_KEEP_RECENT_TOKENS"] = "40"
    os.environ["CONTEXT_COMPACTION_RESERVE_TOKENS"] = "1024"
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


class _FakeSummaryModel:
    """只实现 ``bind`` + ``ainvoke``：摘要请求的调用面就这么窄。"""

    def __init__(self, *, text: str = "旧摘要内容", finish_reason: str = "stop"):
        self.text = text
        self.finish_reason = finish_reason
        self.bound: dict = {}
        self.prompts: list[list] = []
        self.fail: Exception | None = None

    def bind(self, **kwargs):
        self.bound.update(kwargs)
        return self

    async def ainvoke(self, messages):
        self.prompts.append(list(messages))
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(
            content=self.text,
            response_metadata={"finish_reason": self.finish_reason},
            usage_metadata={
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
            },
        )


async def _seed(session, *, message_count: int = 8):
    """建平台/Agent/终端用户/会话与一批已完成消息，返回 (会话, 消息行)。"""

    platform = Platform(name="Acme", code="acme")
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Support", slug="support")
    end_user = PlatformEndUser(platform_id=platform.id, external_user_id="external_1")
    session.add_all([agent, end_user])
    await session.flush()
    conversation = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        platform_end_user_id=end_user.id,
        title="上下文压缩",
    )
    session.add(conversation)
    await session.flush()
    rows = []
    for index in range(message_count):
        row = ConversationMessage(
            conversation_id=conversation.id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"第 {index + 1} 轮内容" + "填充" * 20,
            status="completed",
            created_at=datetime.now(UTC),
        )
        session.add(row)
        rows.append(row)
    await session.commit()
    return conversation, rows


def _run(coro_factory):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        async with engine.begin() as connection:
            await connection.run_sync(BaseModel.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                await coro_factory(session)
        finally:
            await engine.dispose()

    with _small_keep_recent():
        asyncio.run(run())


def test_compaction_writes_row_and_is_idempotent_on_repeat():
    async def scenario(session):
        conversation, _rows = await _seed(session)
        repo = ConversationRepository(session)
        history = await repo.list_recent_context_messages(
            conversation.id, since=datetime.now(UTC).replace(year=2000)
        )
        model = _FakeSummaryModel(text="压缩后的旧摘要")
        outcome = await compact_conversation(
            repo=repo,
            conversation_id=conversation.id,
            model=model,
            trigger="manual",
            window_tokens=1_000,
            rows=history,
            current_compaction=None,
        )

        assert outcome.compacted is True
        assert outcome.reason == "compacted"
        assert outcome.tokens_before > outcome.tokens_after
        assert 0 < outcome.percent < 100
        assert model.bound["max_tokens"] == 819  # floor(0.8 * reserve)

        stored = await session.scalar(select(ConversationContextCompaction))
        assert stored is not None
        assert stored.summary == "压缩后的旧摘要"
        assert stored.trigger == "manual"
        assert stored.model_name is None
        # usage 统一按仓库既有口径规整成 prompt/completion/total 三键。
        assert stored.usage == {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
        # 边界必须落在保留区首行，且该行确实是历史中的一行。
        assert stored.first_kept_message_id in {row.id for row in history}

        # 没有新内容时幂等：不产生第二行。
        again = await compact_conversation(
            repo=repo,
            conversation_id=conversation.id,
            model=model,
            trigger="manual",
            window_tokens=1_000,
            rows=history,
            current_compaction=stored,
        )
        assert again.compacted is False
        assert again.reason == "nothing_to_compact"
        total_rows = await session.scalar(
            select(ConversationContextCompaction).with_only_columns(
                ConversationContextCompaction.id
            )
        )
        assert total_rows is not None
        assert len((await session.scalars(select(ConversationContextCompaction))).all()) == 1

    _run(scenario)


def test_truncated_summary_is_rejected_without_writing_row():
    """摘要被长度截断＝不完整，宁可不压缩也不能写坏 checkpoint。"""

    async def scenario(session):
        conversation, _rows = await _seed(session)
        repo = ConversationRepository(session)
        history = await repo.list_recent_context_messages(
            conversation.id, since=datetime.now(UTC).replace(year=2000)
        )
        model = _FakeSummaryModel(finish_reason="length")
        outcome = await compact_conversation(
            repo=repo,
            conversation_id=conversation.id,
            model=model,
            trigger="auto",
            rows=history,
        )

        assert outcome.compacted is False
        assert outcome.reason == "summary_failed"
        assert (await session.scalars(select(ConversationContextCompaction))).all() == []

    _run(scenario)


def test_failed_summary_request_is_rejected_without_writing_row():
    async def scenario(session):
        conversation, _rows = await _seed(session)
        repo = ConversationRepository(session)
        history = await repo.list_recent_context_messages(
            conversation.id, since=datetime.now(UTC).replace(year=2000)
        )
        model = _FakeSummaryModel()
        model.fail = RuntimeError("upstream down")
        outcome = await compact_conversation(
            repo=repo,
            conversation_id=conversation.id,
            model=model,
            trigger="auto",
            rows=history,
        )

        assert outcome.compacted is False
        assert outcome.reason == "summary_failed"
        assert (await session.scalars(select(ConversationContextCompaction))).all() == []

    _run(scenario)


def test_second_compaction_merges_previous_summary():
    """二次压缩必须把旧摘要带进提示词，否则早期决策会被丢掉。"""

    async def scenario(session):
        conversation, rows = await _seed(session, message_count=6)
        repo = ConversationRepository(session)
        history = await repo.list_recent_context_messages(
            conversation.id, since=datetime.now(UTC).replace(year=2000)
        )
        first_model = _FakeSummaryModel(text="第一次摘要：确定了接口契约")
        first = await compact_conversation(
            repo=repo,
            conversation_id=conversation.id,
            model=first_model,
            trigger="manual",
            rows=history,
        )
        assert first.compacted is True

        # 追加更多消息，制造第二次可压缩的增量。
        for index in range(4):
            session.add(
                ConversationMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content=f"新增第 {index} 段" + "增量" * 20,
                    status="completed",
                    created_at=datetime.now(UTC),
                )
            )
        await session.commit()
        grown = await repo.list_recent_context_messages(
            conversation.id, since=datetime.now(UTC).replace(year=2000)
        )
        assert len(grown) > len(history) - rows.index(history[0])

        second_model = _FakeSummaryModel(text="第二次摘要：并入第一次的契约结论")
        second = await compact_conversation(
            repo=repo,
            conversation_id=conversation.id,
            model=second_model,
            trigger="manual",
            rows=grown,
            current_compaction=first.compaction,
        )

        assert second.compacted is True
        prompt = "\n".join(
            str(message.content) for message in second_model.prompts[-1]
        )
        assert "<previous-summary>" in prompt
        assert "第一次摘要：确定了接口契约" in prompt
        assert "保留旧摘要" in prompt
        # 两次压缩各留一行，旧行保留作审计。
        stored = (await session.scalars(select(ConversationContextCompaction))).all()
        assert [item.summary for item in stored] == [
            "第一次摘要：确定了接口契约",
            "第二次摘要：并入第一次的契约结论",
        ]

    _run(scenario)
