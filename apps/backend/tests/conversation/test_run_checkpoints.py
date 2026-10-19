"""运行检查点仓储的单元测试：CAS 抢占、清空上下文与状态语义。

不连真实数据库：用 sqlite 内存库 + aiosqlite 驱动跑仓储的真实 SQL。这样既不需要
Postgres，又保留了 ``expire_on_commit=False`` 的真实会话语义——正是 ③a 出过 bug
的那个坑（Core update 不会同步 identity map），所以不能只做语句编译断言。
测试只建检查点及其外键闭包涉及的表，不触碰向量等 Postgres 专属类型。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
    AsyncEngine,
)
from sqlalchemy.schema import CreateTable

from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopRunCheckpoint,
    Conversation,
)
from app.modules.conversation.repositories import AgentLoopRunCheckpointRepository
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.modules.user.models import User
from app.shared.base_model import BaseModel

TABLE = "agent_loop_run_checkpoints"
CONTEXT_SNAPSHOT = [
    {"type": "system", "content": "你是一个助手"},
    {"type": "human", "content": "帮我把订单标记为已完成"},
]


def _checkpoint_tables() -> list:
    """返回检查点表及其外键闭包（父表排在被引用表之后），按依赖顺序建表。

    只取闭包而不是 ``BaseModel.metadata.create_all``：全量元数据里有 VECTOR 等
    Postgres 专属类型，sqlite 建不出来。
    """

    related: dict[str, object] = {}
    stack = [BaseModel.metadata.tables[TABLE]]
    while stack:
        table = stack.pop()
        if table.name in related:
            continue
        related[table.name] = table
        for foreign_key in table.foreign_keys:
            stack.append(foreign_key.column.table)

    ordered: list = []
    emitted: set[str] = set()

    def emit(table) -> None:
        if table.name in emitted:
            return
        emitted.add(table.name)
        for foreign_key in table.foreign_keys:
            emit(foreign_key.column.table)
        ordered.append(table)

    for table in related.values():
        emit(table)
    return ordered


async def _make_session() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # sqlite 默认不开外键开关，打开它才能验证 CASCADE / RESTRICT 这些 DDL 语义。
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # sqlite 只对字面量 `INTEGER PRIMARY KEY` 做 rowid 自增，而模型主键是
    # BigInteger（PG 上是 bigserial，仓库既有表的统一选择）。这里只在测试 DDL 里
    # 把 id 改写成整数主键，且内联的 UNIQUE 约束会被去掉（sqlite 建表时引用不存在的
    # 表反而会报错），改由一个独立唯一索引承担——两者语义相同，被测的
    # 「loop_run_id 唯一」与「id 自增」都仍然成立。生产类型与约束不受影响。
    dialect = engine.sync_engine.dialect
    table = BaseModel.metadata.tables[TABLE]
    ddl_lines = []
    for line in str(CreateTable(table).compile(dialect=dialect)).splitlines():
        if "CONSTRAINT uq_" in line:
            continue
        # 只改写主键那一行：整串替换会顺带命中 `loop_run_id`/`conversation_id`
        # 这类以 id 结尾的列名（`...id BIGINT NOT NULL` 是它们的子串）。
        line = line.rstrip()
        if line.lstrip().startswith("id BIGINT NOT NULL"):
            line = "\tid INTEGER NOT NULL,"
        ddl_lines.append(line)
    checkpoint_ddl = "\n".join(ddl_lines)

    async with engine.begin() as connection:
        for create_table in _checkpoint_tables():
            if create_table.name == TABLE:
                await connection.execute(text(checkpoint_ddl))
                await connection.execute(
                    text(
                        "CREATE UNIQUE INDEX uq_agent_loop_run_checkpoints_loop_run_id "
                        "ON agent_loop_run_checkpoints (loop_run_id)"
                    )
                )
            else:
                await connection.run_sync(create_table.create)

    return engine, async_sessionmaker(bind=engine, expire_on_commit=False)


async def _seed(session: AsyncSession) -> dict[str, int]:
    """铺一个最小场景：一个平台 + 两条会话（后台用户 / Embed 最终用户）各一个运行。"""

    platform = Platform(name="Acme", code="acme", is_active=True)
    session.add(platform)
    await session.flush()

    agent = Agent(platform_id=platform.id, name="Support", slug="support", is_default=False, is_active=True)
    user = User(name="Admin", email="admin@acme.test", account="admin", password="x", is_active=True)
    end_user = PlatformEndUser(platform_id=platform.id, external_user_id="external_1", is_active=True)
    session.add_all([agent, user, end_user])
    await session.flush()

    internal_conversation = Conversation(
        platform_id=platform.id, agent_id=agent.id, user_id=user.id
    )
    embed_conversation = Conversation(
        platform_id=platform.id, agent_id=agent.id, platform_end_user_id=end_user.id
    )
    session.add_all([internal_conversation, embed_conversation])
    await session.flush()

    internal_loop = AgentLoopRun(
        conversation_id=internal_conversation.id, request_id="req-internal"
    )
    embed_loop = AgentLoopRun(
        conversation_id=embed_conversation.id, request_id="req-embed"
    )
    session.add_all([internal_loop, embed_loop])
    await session.commit()

    return {
        "platform_id": platform.id,
        "agent_id": agent.id,
        "user_id": user.id,
        "platform_end_user_id": end_user.id,
        "internal_conversation_id": internal_conversation.id,
        "embed_conversation_id": embed_conversation.id,
        "internal_loop_id": internal_loop.id,
        "embed_loop_id": embed_loop.id,
    }


async def _prepare() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], dict[str, int]]:
    engine, factory = await _make_session()
    async with factory() as session:
        ids = await _seed(session)
    return engine, factory, ids


def _create_kwargs(ids: dict[str, int], **overrides) -> dict:
    kwargs = {
        "loop_run_id": ids["internal_loop_id"],
        "conversation_id": ids["internal_conversation_id"],
        "platform_id": ids["platform_id"],
        "agent_id": ids["agent_id"],
        "confirmation_source": "tool_confirmations",
        "confirmation_id": 77,
        "tool_call_id": "call_1",
        "tool_name": "create_task",
        "tool_type": "builtin_tool",
        "side_effect": "write",
        "context": list(CONTEXT_SNAPSHOT),
        "expires_at": datetime.now(UTC) + timedelta(seconds=300),
        "user_id": ids["user_id"],
    }
    kwargs.update(overrides)
    return kwargs


def test_claim_returns_false_when_status_is_not_pending() -> None:
    """CAS 的比较条件是 status == 'pending'，任何非 pending 状态都抢不到。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.create(**_create_kwargs(ids))
                checkpoint = await repo.get_by_loop_run(ids["internal_loop_id"])
                assert checkpoint is not None
                assert checkpoint.status == "pending"

                # 第一次抢占成功，状态变成 resolved。
                assert await repo.claim(ids["internal_loop_id"], "resolved") is True
                # 已经是 resolved，第二次抢占必须失败（并发解决只有一个能生效）。
                assert await repo.claim(ids["internal_loop_id"], "resolved") is False
                assert await repo.claim(ids["internal_loop_id"], "expired") is False

                # Core update 不走 identity map，这里显式重读确认落库状态。
                await session.refresh(checkpoint)
                assert checkpoint.status == "resolved"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_claim_returns_false_for_expired_and_consumed() -> None:
    """expired / consumed 同样是终态，不能再被抢占。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.create(**_create_kwargs(ids))

                assert await repo.claim(ids["internal_loop_id"], "expired") is True
                assert await repo.claim(ids["internal_loop_id"], "resolved") is False
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.mark_consumed(ids["embed_loop_id"])  # 不存在时静默返回
                assert await repo.claim(ids["embed_loop_id"], "resolved") is False
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_claim_returns_false_when_checkpoint_missing() -> None:
    """没有检查点的运行（例如不存在或已删除）抢占失败，不抛异常。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.create(**_create_kwargs(ids))
                assert await repo.claim(999_999, "resolved") is False
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_mark_consumed_clears_context_and_sets_consumed_at() -> None:
    """续跑消费后：status=consumed、consumed_at 非空、context 被清空。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                checkpoint = await repo.create(**_create_kwargs(ids))
                assert checkpoint.context == CONTEXT_SNAPSHOT

                await repo.mark_consumed(ids["internal_loop_id"])
                # expire_on_commit=False 下，实例赋值 + commit 必须让调用方手里的
                # 对象直接是新状态（不需要再 refresh）。
                assert checkpoint.status == "consumed"
                assert checkpoint.consumed_at is not None
                assert checkpoint.context == []

                await session.refresh(checkpoint)
                assert checkpoint.status == "consumed"
                assert checkpoint.consumed_at is not None
                assert checkpoint.context == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_mark_expired_clears_context() -> None:
    """惰性过期收尾：status=expired 且不再留存模型上下文。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                checkpoint = await repo.create(**_create_kwargs(ids))

                await repo.mark_expired(ids["internal_loop_id"])
                assert checkpoint.status == "expired"
                assert checkpoint.context == []

                await session.refresh(checkpoint)
                assert checkpoint.status == "expired"
                # 过期是终态，过期后不能再被解决。
                assert await repo.claim(ids["internal_loop_id"], "resolved") is False
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_mark_consumed_and_expired_ignore_missing_checkpoint() -> None:
    """收尾方法对不存在的运行是空操作，不抛异常。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.mark_consumed(ids["embed_loop_id"])
                await repo.mark_expired(ids["embed_loop_id"])
                assert await repo.get_by_loop_run(ids["embed_loop_id"]) is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_get_by_loop_run_reads_back_full_row() -> None:
    """读回的行必须带全续跑需要的字段（含 Embed 主体与 context 快照）。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.create(
                    **_create_kwargs(
                        ids,
                        loop_run_id=ids["embed_loop_id"],
                        conversation_id=ids["embed_conversation_id"],
                        user_id=None,
                        platform_end_user_id=ids["platform_end_user_id"],
                        confirmation_source="mcp_tool_confirmations",
                    )
                )

                row = await repo.get_by_loop_run(ids["embed_loop_id"])
                assert row is not None
                assert row.loop_run_id == ids["embed_loop_id"]
                assert row.conversation_id == ids["embed_conversation_id"]
                assert row.platform_id == ids["platform_id"]
                assert row.agent_id == ids["agent_id"]
                assert row.user_id is None
                assert row.platform_end_user_id == ids["platform_end_user_id"]
                assert row.confirmation_source == "mcp_tool_confirmations"
                assert row.confirmation_id == 77
                assert row.tool_call_id == "call_1"
                assert row.tool_name == "create_task"
                assert row.context == CONTEXT_SNAPSHOT
                assert row.status == "pending"
                assert row.resolved_at is None
                assert row.consumed_at is None

                assert await repo.get_by_loop_run(ids["internal_loop_id"]) is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_loop_run_id_is_unique() -> None:
    """loop_run_id 唯一：一个运行最多一个待确认检查点（并发重复挂起由 DB 挡住）。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.create(**_create_kwargs(ids))
                try:
                    await repo.create(**_create_kwargs(ids))
                except Exception as error:  # IntegrityError：唯一索引兜底
                    assert "agent_loop_run_checkpoints" in str(error)
                else:  # pragma: no cover - 唯一约束失效才会走到
                    raise AssertionError("重复 loop_run_id 必须被唯一约束拒绝")
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_checkpoint_deleted_with_loop_run_cascade() -> None:
    """运行被删时检查点跟着删（CASCADE），不会留下指向空运行的悬挂检查点。"""

    async def scenario() -> None:
        engine, factory, ids = await _prepare()
        try:
            async with factory() as session:
                repo = AgentLoopRunCheckpointRepository(session)
                await repo.create(**_create_kwargs(ids))

                loop = await session.get(AgentLoopRun, ids["internal_loop_id"])
                assert loop is not None
                await session.delete(loop)
                await session.commit()

                remaining = await session.scalar(
                    select(AgentLoopRunCheckpoint).where(
                        AgentLoopRunCheckpoint.loop_run_id == ids["internal_loop_id"]
                    )
                )
                assert remaining is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())
