"""后台会话记录读接口的用例（sqlite 内存库 + 真实路由）。

覆盖 spec 验收第 1–5 条中可在 sqlite 上判定的部分：
1. 平台管理员校验失败一律 404（非成员、以及管理员访问其它平台）；
2. 主体列表只列「有会话」的主体，计数与最近活跃时间与库内一致，终端用户显示名
   按 display_name → external_user_id 回退；
3. 后台消息接口与 embed 同接口在相同数据下逐字段相同（含 loop.steps）；
4. 软删除默认从列表隐藏、显式 status=deleted 可见，且消息与用量记录保留；
5. agent_id / 日期区间 / keyword / principal_type+principal_id 四维筛选各自生效。

HTTP 面用 ``httpx.ASGITransport`` 走真实路由并覆盖 ``get_db_session`` /
``require_current_active_user``；lifespan 不会被 ASGITransport 触发，因此
``get_db_session`` 必须覆盖，否则会去连真实数据库（与 ``tests/workflows`` 同一写法）。

说明：sqlite 只验证查询口径与状态流转；真实 PostgreSQL 上的行为与前端真机点击由
``tools/harness/verify/2026-10-13-admin-conversation-history.sh`` 记录。
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from main import app
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.agent.models import Agent
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
    ConversationMessage,
    ModelUsageRecord,
)
from app.modules.conversation.repositories import (
    CONVERSATION_STATUS_DELETED,
    ConversationRepository,
)
from app.modules.conversation.services import (
    get_console_conversation,
    list_console_conversation_messages,
    list_console_conversation_principals,
    list_console_conversations,
)
from app.modules.embed.models import PlatformEndUser
from app.modules.embed.services import get_embed_message_snapshot
from app.modules.platform.models import Platform, PlatformAdmin
from app.modules.user.models import User
from app.shared.base_model import BaseModel

PREFIX = "/api/v1/platforms"


async def _make_session():
    """建一个 sqlite 内存库（开启外键约束），返回 (engine, session_factory)。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@contextlib.asynccontextmanager
async def _client(session_factory, user_id: int):
    """以 `user_id` 的身份访问测试 app，退出时清理依赖覆盖。"""

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[require_current_active_user] = lambda: SimpleNamespace(
        id=user_id, is_active=True
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


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


def _at(day: int) -> datetime:
    return datetime(2026, 10, day, 3, 0, tzinfo=UTC)


async def _seed(session):
    """建两个平台、三个 Agent、两个后台用户、三个终端用户与五个会话。

    数据刻意覆盖最容易写错的四种边界：后台用户主体、有显示名的终端用户、只有外部
    ID 的终端用户、已软删除的会话、以及另一个平台的会话。
    """
    platform = Platform(name="Acme", code="acme", is_active=True)
    other_platform = Platform(name="Globex", code="globex", is_active=True)
    session.add_all([platform, other_platform])
    await session.flush()

    agent = Agent(platform_id=platform.id, name="客服机器人", slug="support")
    other_agent = Agent(platform_id=platform.id, name="运营机器人", slug="ops")
    foreign_agent = Agent(
        platform_id=other_platform.id, name="他平台机器人", slug="foreign"
    )
    session.add_all([agent, other_agent, foreign_agent])
    await session.flush()

    admin = User(name="后台管理员", email="admin@acme.test", account="admin", password="x")
    outsider = User(
        name="非成员", email="outsider@acme.test", account="outsider", password="x"
    )
    session.add_all([admin, outsider])
    await session.flush()
    # 平台成员关系是后台接口唯一的权限依据：outsider 刻意不写入。
    session.add(PlatformAdmin(platform_id=platform.id, user_id=admin.id))
    await session.flush()

    named_end_user = PlatformEndUser(
        platform_id=platform.id, external_user_id="ext-1", display_name="终端小明"
    )
    anonymous_end_user = PlatformEndUser(platform_id=platform.id, external_user_id="ext-2")
    foreign_end_user = PlatformEndUser(
        platform_id=other_platform.id, external_user_id="ext-3"
    )
    session.add_all([named_end_user, anonymous_end_user, foreign_end_user])
    await session.flush()

    # 后台用户主体：2 条消息 + 1 次 Loop（2 步）+ 1 条用量记录。
    user_conversation = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        user_id=admin.id,
        title="后台用户会话",
        status="active",
        created_at=_at(2),
        updated_at=_at(2),
    )
    # 终端用户主体（有显示名）：承载验收 3 的 create/embed 投影逐字段比对。
    end_user_conversation = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        platform_end_user_id=named_end_user.id,
        title="终端会话",
        status="active",
        created_at=_at(6),
        updated_at=_at(6),
    )
    # 终端用户主体（无显示名）：显示名必须回退到 external_user_id；0 条消息。
    no_display_conversation = Conversation(
        platform_id=platform.id,
        agent_id=other_agent.id,
        platform_end_user_id=anonymous_end_user.id,
        title="无显示名终端会话",
        status="active",
        created_at=_at(8),
        updated_at=_at(8),
    )
    # 已软删除：默认列表不可见，但消息与用量都还在。
    deleted_conversation = Conversation(
        platform_id=platform.id,
        agent_id=agent.id,
        user_id=admin.id,
        title="已删除会话",
        status=CONVERSATION_STATUS_DELETED,
        created_at=_at(3),
        updated_at=_at(3),
    )
    # 另一个平台的会话：管理员访问该平台必须 404，且跨平台筛选不得泄露到 Acme。
    foreign_conversation = Conversation(
        platform_id=other_platform.id,
        agent_id=foreign_agent.id,
        platform_end_user_id=foreign_end_user.id,
        title="他平台会话",
        status="active",
        created_at=_at(9),
        updated_at=_at(9),
    )
    session.add_all(
        [
            user_conversation,
            end_user_conversation,
            no_display_conversation,
            deleted_conversation,
            foreign_conversation,
        ]
    )
    await session.flush()

    await _add_message(session, user_conversation.id, "user", "你好，帮我查订单")
    user_answer = await _add_message(session, user_conversation.id, "assistant", "订单已发货")
    await _add_message(session, end_user_conversation.id, "user", "终端提问")
    end_user_answer = await _add_message(
        session, end_user_conversation.id, "assistant", "终端回答"
    )
    await _add_message(session, deleted_conversation.id, "user", "删除前的最后一句")

    user_loop = AgentLoopRun(
        conversation_id=user_conversation.id,
        assistant_message_id=user_answer.id,
        request_id="req-user-1",
        status="completed",
        summary="已答复",
        run_metadata={},
    )
    end_user_loop = AgentLoopRun(
        conversation_id=end_user_conversation.id,
        assistant_message_id=end_user_answer.id,
        request_id="req-end-user-1",
        status="completed",
        summary="已完成答复",
        run_metadata={},
    )
    session.add_all([user_loop, end_user_loop])
    await session.flush()
    session.add_all(
        [
            AgentLoopStep(
                loop_run_id=user_loop.id,
                sequence=1,
                step_type="tool",
                title="查询订单",
                status="completed",
                input_summary="订单号 A1",
                output_summary="已发货",
                citation_refs=[],
                attempt=1,
                step_metadata={},
            ),
            AgentLoopStep(
                loop_run_id=user_loop.id,
                sequence=2,
                step_type="generate",
                title="生成答复",
                status="completed",
                citation_refs=[],
                attempt=1,
                step_metadata={},
            ),
            AgentLoopStep(
                loop_run_id=end_user_loop.id,
                sequence=1,
                step_type="tool",
                title="检索订单",
                status="completed",
                input_summary="订单号 B2",
                output_summary="已签收",
                tool_name="search_order",
                citation_refs=[],
                attempt=1,
                step_metadata={},
            ),
        ]
    )
    session.add_all(
        [
            ModelUsageRecord(
                platform_id=platform.id,
                agent_id=agent.id,
                user_id=admin.id,
                conversation_id=user_conversation.id,
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
            ),
            ModelUsageRecord(
                platform_id=platform.id,
                agent_id=agent.id,
                platform_end_user_id=named_end_user.id,
                conversation_id=end_user_conversation.id,
                prompt_tokens=5,
                completion_tokens=7,
                total_tokens=12,
            ),
            ModelUsageRecord(
                platform_id=platform.id,
                agent_id=agent.id,
                user_id=admin.id,
                conversation_id=deleted_conversation.id,
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        ]
    )
    await session.flush()

    return SimpleNamespace(
        platform_id=platform.id,
        other_platform_id=other_platform.id,
        agent_id=agent.id,
        other_agent_id=other_agent.id,
        admin_id=admin.id,
        outsider_id=outsider.id,
        named_end_user_id=named_end_user.id,
        anonymous_end_user_id=anonymous_end_user.id,
        user_conversation_id=user_conversation.id,
        end_user_conversation_id=end_user_conversation.id,
        no_display_conversation_id=no_display_conversation.id,
        deleted_conversation_id=deleted_conversation.id,
        foreign_conversation_id=foreign_conversation.id,
    )


def _item_ids(body) -> list[int]:
    return [item["id"] for item in body["data"]["items"]]


def test_non_admin_and_cross_platform_reads_are_404():
    """验收 1：非平台成员、以及管理员访问其它平台，一律 404 而非 403。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                await session.commit()

            paths = [
                "/conversation-principals",
                "/conversations",
                f"/conversations/{meta.user_conversation_id}",
                f"/conversations/{meta.user_conversation_id}/messages",
            ]
            base = f"{PREFIX}/{meta.platform_id}"
            async with _client(session_factory, meta.outsider_id) as client:
                for path in paths:
                    response = await client.get(f"{base}{path}")
                    assert response.status_code == 404, path
                    assert response.json()["success"] is False
                deleted = await client.delete(
                    f"{PREFIX}/{meta.platform_id}/conversations/{meta.user_conversation_id}"
                )
                assert deleted.status_code == 404

            # 管理员访问别的平台同样 404（不是「看得到但是空」）。
            async with _client(session_factory, meta.admin_id) as client:
                foreign = await client.get(
                    f"{PREFIX}/{meta.other_platform_id}/conversations"
                )
                assert foreign.status_code == 404
                foreign_delete = await client.delete(
                    f"{PREFIX}/{meta.other_platform_id}/conversations/"
                    f"{meta.foreign_conversation_id}"
                )
                assert foreign_delete.status_code == 404

                # 本人是管理员的平台则正常返回，避免「全都 404」式的假通过。
                own = await client.get(f"{PREFIX}/{meta.platform_id}/conversations")
                assert own.status_code == 200
                assert own.json()["code"] == 0

            # 越权删除必须没有产生任何副作用。
            async with session_factory() as session:
                conversation = await session.get(Conversation, meta.user_conversation_id)
                assert conversation.status == "active"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_principals_only_lists_principals_with_conversations():
    """验收 2：主体聚合只列有会话的主体，计数/最近活跃与库内一致，显示名可回退。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                await session.commit()

                page = await list_console_conversation_principals(
                    session, meta.platform_id
                )
                by_key = {
                    (item["principal_type"], item["principal_id"]): item
                    for item in page["items"]
                }
                # 只有「有会话」的主体：非成员、其它平台的终端用户都不出现。
                assert set(by_key) == {
                    ("user", meta.admin_id),
                    ("end_user", meta.named_end_user_id),
                    ("end_user", meta.anonymous_end_user_id),
                }
                user_item = by_key[("user", meta.admin_id)]
                assert user_item["conversation_count"] == 1
                assert user_item["display_name"] == "后台管理员"
                assert by_key[("end_user", meta.named_end_user_id)][
                    "display_name"
                ] == "终端小明"
                # 无 display_name 时回退到 external_user_id。
                assert by_key[("end_user", meta.anonymous_end_user_id)][
                    "display_name"
                ] == "ext-2"
                assert page["total"] == 3
                # 最近产生会话的排在最前：10-08 > 10-06 > 10-02。
                assert page["items"][0]["principal_id"] == meta.anonymous_end_user_id

                # 显式带上已删除会话后，后台用户的计数随之变为 2。
                with_deleted = await list_console_conversation_principals(
                    session, meta.platform_id, include_deleted=True
                )
                with_deleted_map = {
                    (item["principal_type"], item["principal_id"]): item
                    for item in with_deleted["items"]
                }
                assert with_deleted_map[("user", meta.admin_id)][
                    "conversation_count"
                ] == 2
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_admin_messages_payload_is_identical_to_embed_projection():
    """验收 3：后台消息接口与 embed 同接口在同一份数据上逐字段相同。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                await session.commit()
                repo = ConversationRepository(session)

                admin_payload = await list_console_conversation_messages(
                    session, meta.platform_id, meta.end_user_conversation_id
                )
                embed_payload = await get_embed_message_snapshot(
                    repo,
                    conversation_id=meta.end_user_conversation_id,
                    claims={
                        "platform_id": meta.platform_id,
                        "agent_id": meta.agent_id,
                        "sub": str(meta.named_end_user_id),
                    },
                )
                assert admin_payload == embed_payload
                # 投影里必须真的带上 Agent Loop 步骤，否则「相同」很容易空对空通过。
                assistant = [item for item in admin_payload if item["role"] == "assistant"][0]
                assert assistant["loop"]["steps"][0]["title"] == "检索订单"
                assert assistant["loop"]["requestId"] == "req-end-user-1"

                # 后台接口同样能拿到后台用户主体的 Loop（embed 侧拿不到，这是扩权点）。
                user_payload = await list_console_conversation_messages(
                    session, meta.platform_id, meta.user_conversation_id
                )
                user_assistant = [
                    item for item in user_payload if item["role"] == "assistant"
                ][0]
                assert [step["title"] for step in user_assistant["loop"]["steps"]] == [
                    "查询订单",
                    "生成答复",
                ]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_soft_delete_hides_from_default_list_but_keeps_everything():
    """验收 4：删除后默认列表隐藏、显式 status=deleted 可见，消息与用量保留。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                await session.commit()

            async with _client(session_factory, meta.admin_id) as client:
                base = f"{PREFIX}/{meta.platform_id}"
                # 默认列表不含已软删除的会话。
                default_list = await client.get(f"{base}/conversations", params={"page_size": 100})
                assert default_list.status_code == 200
                assert meta.deleted_conversation_id not in _item_ids(default_list.json())

                # 显式指定 status=deleted 时可见。
                deleted_list = await client.get(
                    f"{base}/conversations",
                    params={"status": "deleted", "page_size": 100},
                )
                assert _item_ids(deleted_list.json()) == [meta.deleted_conversation_id]

                # 已删除会话仍可读消息与用量。
                messages = await client.get(
                    f"{base}/conversations/{meta.deleted_conversation_id}/messages"
                )
                assert messages.status_code == 200
                assert [item["content"] for item in messages.json()["data"]] == [
                    "删除前的最后一句"
                ]
                detail = await client.get(
                    f"{base}/conversations/{meta.deleted_conversation_id}"
                )
                assert detail.json()["data"]["usage"]["total_tokens"] == 2

                # 再次删除同一会话：按不存在处理。
                again = await client.delete(
                    f"{base}/conversations/{meta.deleted_conversation_id}"
                )
                assert again.status_code == 404

            async with session_factory() as session:
                conversation = await session.get(Conversation, meta.deleted_conversation_id)
                assert conversation.status == CONVERSATION_STATUS_DELETED
                message_count = await session.scalar(
                    select(func.count(ConversationMessage.id)).where(
                        ConversationMessage.conversation_id == meta.deleted_conversation_id
                    )
                )
                usage_count = await session.scalar(
                    select(func.count(ModelUsageRecord.id)).where(
                        ModelUsageRecord.conversation_id == meta.deleted_conversation_id
                    )
                )
                assert message_count == 1
                assert usage_count == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_filters_agent_date_keyword_and_principal():
    """验收 5：四个筛选维度各自生效且可组合，keyword 覆盖标题与末条消息两个来源。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                await session.commit()

                async def list_ids(**filters) -> list[int]:
                    page = await list_console_conversations(
                        session, meta.platform_id, page_size=100, **filters
                    )
                    return [item["id"] for item in page["items"]]

                # agent 维度
                assert await list_ids(agent_id=meta.other_agent_id) == [
                    meta.no_display_conversation_id
                ]
                # 日期维度（半开区间，10-05 起的窗口不含 10-02/10-03 两条）
                from datetime import date

                assert await list_ids(
                    start_date=date(2026, 10, 5), end_date=date(2026, 10, 7)
                ) == [meta.end_user_conversation_id]
                # 主体维度：只影响后台用户主体的会话
                assert await list_ids(
                    principal_type="user", principal_id=meta.admin_id
                ) == [meta.user_conversation_id]
                assert await list_ids(
                    principal_type="end_user", principal_id=meta.named_end_user_id
                ) == [meta.end_user_conversation_id]
                # keyword 命中标题
                assert await list_ids(keyword="无显示名终端") == [
                    meta.no_display_conversation_id
                ]
                # keyword 命中末条消息摘要（标题完全不含这串字）
                assert await list_ids(keyword="订单已发货") == [
                    meta.user_conversation_id
                ]
                # 组合：agent + keyword，两者必须同时满足
                assert await list_ids(agent_id=meta.agent_id, keyword="终端") == [
                    meta.end_user_conversation_id
                ]
                # keyword 是子串匹配：同一关键词在另一个 Agent 下会命中标题包含它的会话
                assert await list_ids(
                    agent_id=meta.other_agent_id, keyword="终端会话"
                ) == [meta.no_display_conversation_id]
                # 关键词命中别人的会话内容时，不属于该 Agent 的会话仍必须被排除
                assert await list_ids(
                    agent_id=meta.other_agent_id, keyword="订单已发货"
                ) == []
                # 计数与列表同源：total 必须与实际返回的 items 条数一致
                page = await list_console_conversations(
                    session, meta.platform_id, keyword="终端"
                )
                assert page["total"] == 2
                assert len(page["items"]) == 2
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_detail_reports_usage_and_preview():
    """会话详情：用量汇总来自 model_usage_records，列表预览为单行摘要。"""

    async def run():
        engine, session_factory = await _make_session()
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                await session.commit()

                detail = await get_console_conversation(
                    session, meta.platform_id, meta.user_conversation_id
                )
                assert detail["usage"] == {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                    "record_count": 1,
                }
                assert detail["agent_name"] == "客服机器人"
                assert detail["principal_name"] == "后台管理员"
                assert detail["message_count"] == 2
                assert detail["last_message_preview"] == "订单已发货"
        finally:
            await engine.dispose()

    asyncio.run(run())
