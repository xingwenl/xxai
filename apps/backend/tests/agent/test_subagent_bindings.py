"""子智能体绑定：候选收窄、服务层校验、自克隆参数与读侧投影。

覆盖 `docs/harness/requests/2026-10-21-subagent-bindings/spec.md` 的验收 2、3、4、5
中不依赖真实模型的判定点：
- 绑定存在时只把「绑定内 + 已发布 + 启用 + 同平台」的子 Agent 当候选；没有绑定时
  回退全平台已发布（排除自己）；
- 自指 / 重复 / 跨平台 / 不存在的绑定被拒；
- `delegate_tasks` 允许省略 agent（自克隆）并接受 role，非候选 slug 整体拒绝且给出可用清单；
- 读侧 delegatedRuns 的 usage / mode 只在有值时出现。
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
import app.modules.agent.repositories as agent_repositories
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.services import (
    list_subagent_bindings,
    replace_subagent_bindings,
)
from app.modules.conversation.serializers import (
    build_delegated_run_payload,
    load_delegated_runs,
)
from app.modules.platform.models import Platform
from app.modules.tools.business import delegate_tasks as delegate_module
from app.shared.base_model import BaseModel
from app.shared.exceptions import BadRequestException, NotFoundException


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _add_agent(
    session,
    platform_id: int,
    slug: str,
    *,
    published: bool = True,
    active: bool = True,
) -> Agent:
    agent = Agent(platform_id=platform_id, name=f"Bot-{slug}", slug=slug, is_active=active)
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt=f"你是 {slug}",
        temperature=0.2,
        model_options={},
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC) if published else None,
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    await session.flush()
    return agent


def test_bindings_narrow_candidates_and_fallback_to_platform() -> None:
    """有绑定只看绑定；没绑定回退全平台已发布（排除自己）。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            other_platform = Platform(name="Other", code="other")
            session.add_all([platform, other_platform])
            await session.flush()
            parent = await _add_agent(session, platform.id, "parent")
            alpha = await _add_agent(session, platform.id, "alpha")
            disabled = await _add_agent(session, platform.id, "paused", active=False)
            draft = await _add_agent(session, platform.id, "draft", published=False)
            ghost = await _add_agent(session, platform.id, "ghost")
            stranger = await _add_agent(session, other_platform.id, "stranger")
            plain_parent = await _add_agent(session, platform.id, "plain")
            await session.commit()

            repo = AgentRepository(session)
            data = await replace_subagent_bindings(
                repo,
                parent.id,
                [(alpha.id, True), (disabled.id, True), (draft.id, False)],
                platform_id=platform.id,
            )
            assert data["fallback"] is False
            assert [item["child_agent_id"] for item in data["items"]] == [
                alpha.id,
                disabled.id,
                draft.id,
            ]
            assert [item["sort_order"] for item in data["items"]] == [0, 1, 2]
            assert [item["enabled"] for item in data["items"]] == [True, True, False]
            assert data["items"][2]["published"] is False

            # 候选：绑定内 + 已发布 + 启用 + 同平台 + 排除自己
            candidates = await repo.list_delegatable_agents(platform.id, parent.id)
            assert [agent.slug for agent in candidates] == ["alpha"]
            assert disabled.id not in [agent.id for agent in candidates]
            assert draft.id not in [agent.id for agent in candidates]
            assert ghost.id not in [agent.id for agent in candidates]
            assert stranger.id not in [agent.id for agent in candidates]

            # 可加绑定清单：排除自己、已绑定的、未发布/停用的
            available = await repo.list_subagent_available_agents(platform.id, parent.id)
            assert "ghost" in [agent.slug for agent in available]
            assert "alpha" not in [agent.slug for agent in available]
            assert "paused" not in [agent.slug for agent in available]
            assert "draft" not in [agent.slug for agent in available]

            # 全部绑定停用/未发布也算「配置过」：不回退全平台（否则等于绕开配置）
            await replace_subagent_bindings(
                repo, parent.id, [(alpha.id, False)], platform_id=platform.id
            )
            narrowed = await list_subagent_bindings(repo, parent.id, platform_id=platform.id)
            assert narrowed["fallback"] is False
            assert await repo.list_delegatable_agents(platform.id, parent.id) == []

            # 没有任何绑定的父 Agent：回退全平台已发布，且排除自己
            fallback = await list_subagent_bindings(
                repo, plain_parent.id, platform_id=platform.id
            )
            assert fallback["fallback"] is True
            assert fallback["items"] == []
            fallback_candidates = await repo.list_delegatable_agents(
                platform.id, plain_parent.id
            )
            slugs = [agent.slug for agent in fallback_candidates]
            assert "parent" in slugs and "alpha" in slugs and "ghost" in slugs
            assert "plain" not in slugs
            assert "paused" not in slugs and "draft" not in slugs

        await engine.dispose()

    asyncio.run(run())


def test_replace_bindings_rejects_self_duplicate_and_foreign_agents() -> None:
    """自指 / 重复 / 跨平台 / 不存在的子 Agent 都不能落库。"""

    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            other_platform = Platform(name="Other", code="other")
            session.add_all([platform, other_platform])
            await session.flush()
            parent = await _add_agent(session, platform.id, "parent")
            child = await _add_agent(session, platform.id, "child")
            stranger = await _add_agent(session, other_platform.id, "stranger")
            await session.commit()
            repo = AgentRepository(session)

            try:
                await replace_subagent_bindings(
                    repo, parent.id, [(parent.id, True)], platform_id=platform.id
                )
                raise AssertionError("自指绑定应被拒绝")
            except BadRequestException:
                pass

            try:
                await replace_subagent_bindings(
                    repo,
                    parent.id,
                    [(child.id, True), (child.id, False)],
                    platform_id=platform.id,
                )
                raise AssertionError("重复绑定应被拒绝")
            except BadRequestException:
                pass

            for foreign_id in (stranger.id, 999999):
                try:
                    await replace_subagent_bindings(
                        repo, parent.id, [(foreign_id, True)], platform_id=platform.id
                    )
                    raise AssertionError("跨平台/不存在的绑定应被拒绝")
                except NotFoundException:
                    pass

            assert await repo.has_subagent_bindings(parent.id) is False

        await engine.dispose()

    asyncio.run(run())


def test_delegate_arguments_support_self_clone_and_role() -> None:
    """agent 可省略（自克隆），role 只在自克隆时有意义且受长度限制。"""

    tasks = delegate_module._validate_arguments(
        {
            "tasks": [
                {"task": "处理订单"},
                {"agent": "alpha", "task": "处理退款"},
                {"task": "核对金额", "role": "只负责核对金额"},
            ]
        },
        max_tasks=8,
    )
    assert tasks[0]["agent"] is None
    assert tasks[0]["role"] is None
    assert tasks[1]["agent"] == "alpha"
    assert tasks[2]["role"] == "只负责核对金额"

    # 自克隆同 role 视为重复；不同 role 允许同批出现
    try:
        delegate_module._validate_arguments(
            {"tasks": [{"task": "a"}, {"task": "b"}]}, max_tasks=8
        )
        raise AssertionError("同批同角色的自克隆应被判重复")
    except Exception as error:  # BusinessToolError
        assert getattr(error, "code", None) == "duplicate_agent"

    same_batch = delegate_module._validate_arguments(
        {
            "tasks": [
                {"task": "a", "role": "核对金额"},
                {"task": "b", "role": "核对库存"},
            ]
        },
        max_tasks=8,
    )
    assert len(same_batch) == 2

    try:
        delegate_module._validate_arguments(
            {"tasks": [{"task": "a", "role": "x" * 501}]}, max_tasks=8
        )
        raise AssertionError("超长 role 应被拒绝")
    except Exception as error:
        assert getattr(error, "code", None) == "invalid_tasks"


def test_resolve_agents_gates_by_catalog_and_supports_self_clone(monkeypatch) -> None:
    """候选外的 slug 整体拒绝并给出可用清单；省略 agent 时目标是父 Agent 自己。"""

    async def run():
        alpha = SimpleNamespace(id=2, slug="alpha", name="Bot-alpha")
        parent = SimpleNamespace(id=1, slug="parent", name="Bot-parent")

        class _FakeRepo:
            def __init__(self, session):
                self.session = session

            async def list_delegatable_agents(
                self, platform_id, parent_agent_id, *, limit=50
            ):
                return [alpha]

            async def get_published_agent(self, agent_id, platform_id):
                return parent if agent_id == parent.id else None

        monkeypatch.setattr(agent_repositories, "AgentRepository", _FakeRepo)
        monkeypatch.setattr(
            delegate_module,
            "get_settings",
            lambda: SimpleNamespace(delegation_max_agents_in_prompt=50),
        )

        bound = await delegate_module._resolve_agents(
            object(),
            platform_id=1,
            parent_agent_id=parent.id,
            tasks=[
                {"agent": "alpha", "role": None, "task": "t1"},
                {"agent": None, "role": "只核对金额", "task": "t2"},
            ],
        )
        assert [mode for _item, _agent, mode in bound] == ["bound", "self"]
        assert bound[0][1] is alpha
        assert bound[1][1] is parent

        try:
            await delegate_module._resolve_agents(
                object(),
                platform_id=1,
                parent_agent_id=parent.id,
                tasks=[{"agent": "ghost", "role": None, "task": "t"}],
            )
            raise AssertionError("候选外 slug 应被拒绝")
        except Exception as error:
            assert getattr(error, "code", None) == "agent_not_available"
            message = error.message
            assert "ghost" in message and "alpha" in message

        # 父 Agent 没有已发布版本时，自克隆不可用
        class _UnpublishedRepo(_FakeRepo):
            async def get_published_agent(self, agent_id, platform_id):
                return None

        monkeypatch.setattr(agent_repositories, "AgentRepository", _UnpublishedRepo)
        try:
            await delegate_module._resolve_agents(
                object(),
                platform_id=1,
                parent_agent_id=parent.id,
                tasks=[{"agent": None, "role": None, "task": "t"}],
            )
            raise AssertionError("无已发布版本时自克隆应被拒绝")
        except Exception as error:
            assert getattr(error, "code", None) == "self_clone_unavailable"

    asyncio.run(run())


def test_delegated_run_projection_carries_usage_and_mode_only_when_present() -> None:
    """delegatedRuns 的 usage / mode 只在有值时出现，键名保持 camelCase。"""

    loop = SimpleNamespace(
        id=7,
        status="completed",
        summary="子运行完成",
        conversation_id=42,
        run_metadata={"delegationMode": "self"},
    )
    payload = build_delegated_run_payload(
        loop,
        agent_slug="parent",
        agent_name="Bot-parent",
        usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        mode="self",
    )
    assert payload["usage"] == {
        "promptTokens": 11,
        "completionTokens": 7,
        "totalTokens": 18,
    }
    assert payload["mode"] == "self"

    # 只有部分字段时 total 用前两者兜底
    partial = build_delegated_run_payload(
        loop, usage={"prompt_tokens": 3, "completion_tokens": 4}
    )
    assert partial["usage"]["totalTokens"] == 7

    # 没有用量/模式的历史运行：投影形状与引入前一致
    plain = build_delegated_run_payload(loop, agent_slug="alpha")
    assert set(plain) == {
        "id",
        "agentSlug",
        "agentName",
        "status",
        "summary",
        "conversationId",
    }

    async def run_load():
        class _Repo:
            async def list_child_loops(self, parent_loop_id):
                return [
                    (SimpleNamespace(id=1, conversation_id=11, status="completed",
                                     summary="a", run_metadata={"delegationMode": "bound"}),
                     "alpha", "Bot-alpha"),
                    (SimpleNamespace(id=2, conversation_id=12, status="completed",
                                     summary="b", run_metadata={}),
                     "parent", "Bot-parent"),
                ]

            async def usage_by_conversation_ids(self, conversation_ids):
                assert conversation_ids == [11, 12]
                return {11: {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}}

        runs = await load_delegated_runs(_Repo(), 1)
        assert runs[0]["mode"] == "bound"
        assert runs[0]["usage"]["totalTokens"] == 11
        assert "mode" not in runs[1] and "usage" not in runs[1]

    asyncio.run(run_load())
