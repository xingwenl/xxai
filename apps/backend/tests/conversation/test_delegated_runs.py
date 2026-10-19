"""委派子运行（`delegate_tasks`）的端到端语义。

覆盖 request `2026-10-15-delegated-subagent-runtime` 里那些「只有真跑一遍才
测得出来」的条款：并发扇出与并发上限、单个子任务失败不中止其余、超时、输出
截断、子运行挂到父运行、父子会话独立、以及「深度恒 1」「子运行不带 MCP」这两条
裁剪规则的落点。

测试用文件型 sqlite 而不是内存库：子运行各自新开 Session 并发写入，内存库的
单连接池会让「并发」退化成串行，那样并发上限的用例就失去意义（与
``tests/workflows/test_runner_parallel.py`` 同一考虑）。

异步用例一律写成「同步 test + 内层 ``async def run()`` + ``asyncio.run``」：
本仓库没有 pytest-asyncio（``pyproject.toml`` 的 dev 依赖里没有它）。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.agent_runtime.contracts import ToolOutcome
from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.conversation.models import AgentLoopRun, AgentLoopStep, Conversation
from app.modules.conversation.runtime import _apply_delegation_policy, tool_step_values
from app.modules.conversation.serializers import build_loop_payload
from app.modules.platform.models import Platform
from app.modules.tools.business import delegate_tasks as delegate_module
from app.modules.tools.business.delegate_tasks import (
    DELEGATE_TASKS_TOOL_NAME,
    MAX_TASKS_IN_SCHEMA,
    TRUNCATION_MARKER,
)
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError
from app.modules.tools.business.registry import BUSINESS_TOOL_REGISTRY
from app.modules.user.models import User
from app.shared.base_model import BaseModel


def _settings(**overrides) -> SimpleNamespace:
    """一份可控的委派配置；默认值对齐 `core.config.Settings`。"""

    values = {
        "delegation_max_tasks": 8,
        "delegation_max_concurrency": 4,
        "delegation_max_iterations": 8,
        "delegation_timeout_seconds": 300,
        "delegation_output_max_bytes": 51200,
        "delegation_max_agents_in_prompt": 50,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _open_db(path: Path):
    """建一个可并发的 sqlite 文件库（外键 + WAL），返回 (engine, session_factory)。"""

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _configure(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # 并发子运行会短时间争抢写锁；没有 busy_timeout 会直接报 database is locked。
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _with_db(tmp_path: Path, body: Callable[[object], Awaitable[None]]) -> None:
    """在一次性文件库上跑异步用例，结束时释放连接。"""

    async def runner():
        engine, factory = await _open_db(tmp_path / "delegation.db")
        try:
            await body(factory)
        finally:
            await engine.dispose()

    asyncio.run(runner())


async def _add_agent(session, *, platform_id: int, slug: str):
    """建一个已发布的 Agent（有 default_version 且 published_at 非空）。"""

    agent = Agent(platform_id=platform_id, name=f"Bot-{slug}", slug=slug)
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="你是子智能体",
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    await session.flush()
    return agent


async def _seed(factory):
    """建平台 + 一个父 Agent + 三个可派子 Agent + 一个用户。"""

    async with factory() as session:
        platform = Platform(name="Delegation", code="delegation", is_active=True)
        session.add(platform)
        await session.flush()
        parent_agent = await _add_agent(session, platform_id=platform.id, slug="parent")
        children = {}
        for slug in ("alpha", "beta", "gamma"):
            children[slug] = await _add_agent(
                session, platform_id=platform.id, slug=slug
            )
        user = User(
            name="Delegator",
            email="delegator@acme.dev",
            account="delegator",
            password="x",
        )
        session.add(user)
        await session.flush()
        await session.commit()
        return SimpleNamespace(
            platform=platform,
            parent_agent=parent_agent,
            children=children,
            user=user,
        )


async def _seed_parent_run(factory, seed):
    """建父会话 + 父运行记录，返回 (conversation, loop)。"""

    async with factory() as session:
        conversation = Conversation(
            platform_id=seed.platform.id,
            agent_id=seed.parent_agent.id,
            user_id=seed.user.id,
            title="父会话",
        )
        session.add(conversation)
        await session.flush()
        loop = AgentLoopRun(
            conversation_id=conversation.id,
            request_id="parent-request",
            status="running",
        )
        session.add(loop)
        await session.flush()
        await session.commit()
        return conversation, loop


def _install_child_runner(
    monkeypatch,
    factory,
    *,
    delay: float = 0.0,
    fail_for: set[int] | None = None,
    content_for: dict[int, str] | None = None,
):
    """把 `execute_unattended_chat` 换成可控替身，返回 (调用记录, 并发峰值状态)。

    替身必须真的往库里写会话与运行记录：父子关系与读侧投影都靠
    `parent_loop_run_id` 串起来，只在内存里返回假对象测不到这条链。
    """

    calls: list[dict] = []
    failing = fail_for or set()
    contents = content_for or {}
    state = {"in_flight": 0, "peak": 0}

    async def fake(session, *, platform_id, agent_id, message, **kwargs):
        index = len(calls)
        calls.append(
            {
                "platform_id": platform_id,
                "agent_id": agent_id,
                "message": message,
                # 每个子运行必须拿自己的 Session：复用网关正在 flush 的那个
                # 会撞 asyncpg 的并发操作错误。
                "session_id": id(session),
                **kwargs,
            }
        )
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        try:
            if delay:
                await asyncio.sleep(delay)
            if agent_id in failing:
                raise RuntimeError("子运行炸了")
            content = contents.get(agent_id, f"{agent_id} 的产出")
            conversation = Conversation(
                platform_id=platform_id,
                agent_id=agent_id,
                user_id=kwargs.get("user_id"),
                platform_end_user_id=kwargs.get("end_user_id"),
                title=message[:40],
            )
            session.add(conversation)
            await session.flush()
            loop = AgentLoopRun(
                conversation_id=conversation.id,
                request_id=f"child-{index}",
                status="completed",
                parent_loop_run_id=kwargs.get("parent_loop_run_id"),
            )
            session.add(loop)
            await session.flush()
            await session.commit()
            return (
                conversation,
                SimpleNamespace(content=content),
                SimpleNamespace(content=content, loop_id=loop.id),
            )
        finally:
            state["in_flight"] -= 1

    from app.modules.conversation import services as conversation_services

    monkeypatch.setattr(
        conversation_services, "execute_unattended_chat", fake, raising=True
    )
    return calls, state


def _patch_runtime(monkeypatch, factory, settings=None):
    """替换模块级依赖：Session 工厂与委派配置。"""

    monkeypatch.setattr(
        delegate_module, "get_session_factory", lambda: factory, raising=True
    )
    monkeypatch.setattr(
        delegate_module, "get_settings", lambda: settings or _settings(), raising=True
    )


async def _call_delegate(factory, seed, loop, *, tasks):
    """以「父运行」身份调一次委派工具。"""

    async with factory() as session:
        context = BusinessToolContext(
            platform_id=seed.platform.id,
            agent_id=seed.parent_agent.id,
            conversation_id=loop.conversation_id,
            user_id=seed.user.id,
            loop_run_id=loop.id,
            session=session,
        )
        return await delegate_module.delegate_tasks({"tasks": tasks}, context)


async def _children(factory, parent_loop_run_id: int) -> list:
    async with factory() as session:
        rows = await session.execute(
            select(AgentLoopRun)
            .where(AgentLoopRun.parent_loop_run_id == parent_loop_run_id)
            .order_by(AgentLoopRun.id)
        )
        return list(rows.scalars())


# --- 注册与参数校验 ---------------------------------------------------------


def test_delegate_tasks_declares_write_side_effect():
    """注册进业务工具与内置工具目录，且声明 write 副作用（派生子运行会写数据）。

    这条断言以前是 ``== "none"``：那时 BusinessTool 根本没有 side_effect 字段，
    暴露层把一切硬编码成 none，于是无人值守下的委派绕过了策略裁决。
    """

    tool = BUSINESS_TOOL_REGISTRY[DELEGATE_TASKS_TOOL_NAME]
    assert tool.input_schema["properties"]["tasks"]["maxItems"] == MAX_TASKS_IN_SCHEMA
    builtin = get_builtin_tool(DELEGATE_TASKS_TOOL_NAME)
    assert builtin is not None
    assert builtin.side_effect == "write"


def test_delegation_without_parent_run_is_refused(tmp_path) -> None:
    """没有父运行（工作流的工具步骤）时明确拒绝，而不是悄悄跑起来。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        async with factory() as session:
            context = BusinessToolContext(
                platform_id=seed.platform.id,
                agent_id=seed.parent_agent.id,
                conversation_id=loop.conversation_id,
                user_id=seed.user.id,
                # 刻意不传 loop_run_id：模拟工作流工具步骤
                session=session,
            )
            with pytest.raises(BusinessToolError) as excinfo:
                await delegate_module.delegate_tasks(
                    {"tasks": [{"agent": "alpha", "task": "做点事"}]}, context
                )
        assert excinfo.value.code == "delegation_requires_parent_run"
        assert await _children(factory, loop.id) == []

    _with_db(tmp_path, body)


@pytest.mark.parametrize(
    ("tasks", "code"),
    [
        ([], "invalid_tasks"),
        ([{"agent": "alpha", "task": ""}], "invalid_tasks"),
        ([{"agent": "", "task": "x"}], "invalid_tasks"),
        ([{"agent": "alpha", "task": "x"}] * 2, "duplicate_agent"),
        ([{"agent": "ghost", "task": "x"}], "agent_not_available"),
    ],
)
def test_invalid_arguments_create_no_child_run(
    tmp_path, monkeypatch, tasks, code
) -> None:
    """参数或 Agent 不合法时整体拒绝：一个子运行都不创建。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory)
        with pytest.raises(BusinessToolError) as excinfo:
            await _call_delegate(factory, seed, loop, tasks=tasks)
        assert excinfo.value.code == code
        assert await _children(factory, loop.id) == []

    _with_db(tmp_path, body)


def test_too_many_tasks_refused(tmp_path, monkeypatch) -> None:
    """超过 max_tasks 直接拒绝，报错里带上实际数量。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory, _settings(delegation_max_tasks=2))
        tasks = [
            {"agent": "alpha", "task": "a"},
            {"agent": "beta", "task": "b"},
            {"agent": "gamma", "task": "c"},
        ]
        with pytest.raises(BusinessToolError) as excinfo:
            await _call_delegate(factory, seed, loop, tasks=tasks)
        assert excinfo.value.code == "too_many_tasks"
        assert await _children(factory, loop.id) == []

    _with_db(tmp_path, body)


# --- 并发扇出 ---------------------------------------------------------------


def test_fanout_is_parallel_and_links_children_to_parent(tmp_path, monkeypatch) -> None:
    """三个子任务并发执行、各自新会话、结果按入参顺序回给模型，子运行挂父运行。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory)
        calls, state = _install_child_runner(monkeypatch, factory, delay=0.2)

        started = time.perf_counter()
        result = await _call_delegate(
            factory,
            seed,
            loop,
            tasks=[
                {"agent": "alpha", "task": "核查 A"},
                {"agent": "beta", "task": "核查 B"},
                {"agent": "gamma", "task": "核查 C"},
            ],
        )
        elapsed = time.perf_counter() - started

        assert [entry["agent"] for entry in result["tasks"]] == [
            "alpha",
            "beta",
            "gamma",
        ]
        assert all(entry["status"] == "completed" for entry in result["tasks"])
        assert (result["succeeded"], result["failed"]) == (3, 0)
        # 串行需要 0.6s；并发下应显著更快（留足慢机器的余量）
        assert elapsed < 0.55
        assert state["peak"] == 3

        children = await _children(factory, loop.id)
        assert len(children) == 3
        assert len({child.conversation_id for child in children}) == 3
        # 深度恒 1 与工具范围收缩都体现在交给子运行的参数上
        assert len({call["session_id"] for call in calls}) == 3
        for call in calls:
            assert call["allow_delegation"] is False
            assert call["platform_tools_only"] is True
            assert call["parent_loop_run_id"] == loop.id
            assert call["max_iterations"] == 8
            assert call["run_as_type"] == "user"
            assert call["user_id"] == seed.user.id
            assert call["end_user_id"] is None
        assert [call["message"] for call in calls] == ["核查 A", "核查 B", "核查 C"]
        # 产物 ID 只走保留键：模型看到的文本里没有它。
        # 子运行 ID 由各自 commit 顺序决定（并发），因此只比集合不比顺序；
        # 回给模型的 tasks 顺序才是入参顺序（上面已断言）。
        assert sorted(result["_metadata"]["delegatedRunIds"], key=int) == sorted(
            (str(child.id) for child in children), key=int
        )

    _with_db(tmp_path, body)


def test_concurrency_cap_is_enforced(tmp_path, monkeypatch) -> None:
    """同时最多 delegation_max_concurrency 个子运行在飞。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory, _settings(delegation_max_concurrency=2))
        _calls, state = _install_child_runner(monkeypatch, factory, delay=0.15)

        async with factory() as session:
            await _add_agent(session, platform_id=seed.platform.id, slug="delta")
            await session.commit()

        started = time.perf_counter()
        result = await _call_delegate(
            factory,
            seed,
            loop,
            tasks=[
                {"agent": "alpha", "task": "1"},
                {"agent": "beta", "task": "2"},
                {"agent": "gamma", "task": "3"},
                {"agent": "delta", "task": "4"},
            ],
        )
        elapsed = time.perf_counter() - started

        assert result["succeeded"] == 4
        assert state["peak"] == 2
        assert elapsed >= 0.25

    _with_db(tmp_path, body)


def test_single_child_failure_does_not_stop_others(tmp_path, monkeypatch) -> None:
    """一个子运行抛错只影响它自己：其余照常完成，失败项带稳定错误码。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory)
        _install_child_runner(monkeypatch, factory, fail_for={seed.children["beta"].id})

        result = await _call_delegate(
            factory,
            seed,
            loop,
            tasks=[
                {"agent": "alpha", "task": "1"},
                {"agent": "beta", "task": "2"},
                {"agent": "gamma", "task": "3"},
            ],
        )

        entries = {entry["agent"]: entry for entry in result["tasks"]}
        assert entries["alpha"]["status"] == "completed"
        assert entries["gamma"]["status"] == "completed"
        assert entries["beta"]["status"] == "failed"
        assert entries["beta"]["error"]["code"] == "delegation_failed"
        assert entries["beta"]["error"]["message"] == "子运行炸了"
        assert (result["succeeded"], result["failed"]) == (2, 1)
        # 失败的子运行没跑起来，不产生运行记录，metadata 里只记成功的
        assert len(result["_metadata"]["delegatedRunIds"]) == 2
        assert len(await _children(factory, loop.id)) == 2

    _with_db(tmp_path, body)


def test_child_timeout_is_reported_as_delegation_timeout(tmp_path, monkeypatch) -> None:
    """子运行超过 delegation_timeout_seconds 时按失败返回，不拖住整个扇出。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory, _settings(delegation_timeout_seconds=0.05))
        _install_child_runner(monkeypatch, factory, delay=0.5)

        started = time.perf_counter()
        result = await _call_delegate(
            factory, seed, loop, tasks=[{"agent": "alpha", "task": "慢慢来"}]
        )
        elapsed = time.perf_counter() - started

        entry = result["tasks"][0]
        assert entry["status"] == "failed"
        assert entry["error"]["code"] == "delegation_timeout"
        assert elapsed < 0.4
        assert "_metadata" not in result

    _with_db(tmp_path, body)


def test_child_output_is_truncated_by_byte_budget(tmp_path, monkeypatch) -> None:
    """子运行输出按字节上限截断并带标记：父模型的上下文不被单个子任务顶穿。"""

    async def body(factory):
        seed = await _seed(factory)
        _conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory, _settings(delegation_output_max_bytes=64))
        _install_child_runner(
            monkeypatch,
            factory,
            content_for={seed.children["alpha"].id: "啊" * 200},
        )

        result = await _call_delegate(
            factory, seed, loop, tasks=[{"agent": "alpha", "task": "写很多"}]
        )

        output = result["tasks"][0]["output"]
        assert output.endswith(TRUNCATION_MARKER)
        assert len(output[: -len(TRUNCATION_MARKER)].encode("utf-8")) <= 64

    _with_db(tmp_path, body)


def test_parent_and_child_conversations_are_independent(tmp_path, monkeypatch) -> None:
    """父子各一条会话：子运行不写父会话。"""

    async def body(factory):
        seed = await _seed(factory)
        conversation, loop = await _seed_parent_run(factory, seed)
        _patch_runtime(monkeypatch, factory)
        _install_child_runner(monkeypatch, factory)

        await _call_delegate(
            factory, seed, loop, tasks=[{"agent": "alpha", "task": "独立跑"}]
        )

        async with factory() as session:
            total = await session.scalar(select(func.count()).select_from(Conversation))
            parent_only = await session.scalar(
                select(func.count())
                .select_from(AgentLoopRun)
                .where(AgentLoopRun.conversation_id == conversation.id)
            )
        assert total == 2  # 父会话 + 一个子会话
        assert parent_only == 1  # 父会话里仍只有父运行

    _with_db(tmp_path, body)


# --- 落库与读侧投影 ---------------------------------------------------------


def test_tool_step_values_carries_delegated_run_ids():
    """工具 outcome 的私有 metadata 进步骤落库字段；没有 metadata 时形状不变。"""

    plain = tool_step_values(
        {"tool": "http_get", "outcome": ToolOutcome(status="completed", result={})}, 2
    )
    assert "step_metadata" not in plain

    event_dict = {
        "tool": DELEGATE_TASKS_TOOL_NAME,
        "outcome": ToolOutcome(
            status="completed",
            result={"tasks": []},
            metadata={"delegatedRunIds": ["7", "8"]},
        ),
    }
    assert tool_step_values(event_dict, 3)["step_metadata"] == {
        "delegatedRunIds": ["7", "8"]
    }


def test_loop_payload_exposes_delegated_runs_only_when_present():
    """读侧投影：有委派才多两个键，没有委派时与改造前逐字相同。"""

    loop = SimpleNamespace(
        id=1, request_id="r", status="completed", summary=None, conversation_id=9
    )
    step = SimpleNamespace(
        id=5,
        sequence=2,
        step_type="builtin",
        title=f"调用工具：{DELEGATE_TASKS_TOOL_NAME}",
        status="succeeded",
        output_summary="工具执行完成",
        input_summary=None,
        thinking_text=None,
        tool_name=DELEGATE_TASKS_TOOL_NAME,
        skill_name=None,
        citation_refs=[],
        error=None,
        step_metadata={"delegatedRunIds": [7, 8]},
    )

    with_delegation = build_loop_payload(
        loop,
        [step],
        [
            {
                "id": "7",
                "agentSlug": "alpha",
                "agentName": "Bot-alpha",
                "status": "completed",
                "summary": None,
                "conversationId": "70",
            }
        ],
    )
    assert with_delegation["steps"][0]["delegatedRunIds"] == ["7", "8"]
    assert with_delegation["delegatedRuns"][0]["agentSlug"] == "alpha"

    step.step_metadata = {}
    plain = build_loop_payload(loop, [step])
    assert "delegatedRuns" not in plain
    assert "delegatedRunIds" not in plain["steps"][0]


def test_step_without_delegation_has_no_extra_keys():
    """未使用委派时步骤投影字段集合与改造前一致（回归口径）。"""

    step = AgentLoopStep(
        loop_run_id=1,
        sequence=1,
        step_type="builtin",
        title="调用工具：http_get",
        status="succeeded",
    )
    payload = build_loop_payload(
        SimpleNamespace(
            id=1, request_id="r", status="completed", summary=None, conversation_id=9
        ),
        [step],
    )
    assert payload["steps"][0]["toolName"] is None
    assert set(payload) == {"id", "requestId", "status", "summary", "steps"}


# --- 工具清单裁剪 -----------------------------------------------------------


def test_apply_delegation_policy_prunes_and_injects_catalog(monkeypatch) -> None:
    """子运行摘掉委派工具；允许委派时把本平台可派清单换进工具描述。"""

    async def body():
        builtin = get_builtin_tool(DELEGATE_TASKS_TOOL_NAME)
        other = get_builtin_tool("ask_user")

        class _Repo:
            def __init__(self, agents):
                self.agents = agents

            async def list_published_active_agents(self, platform_id, *, limit):
                return self.agents[:limit]

        # 没有绑定委派工具：原样返回，逐字不变
        untouched = await _apply_delegation_policy(
            [other], agent_repo=_Repo([]), platform_id=1, allow_delegation=True
        )
        assert untouched == [other]
        assert untouched[0] is other

        # 子运行：委派工具被摘掉
        pruned = await _apply_delegation_policy(
            [builtin, other],
            agent_repo=_Repo([]),
            platform_id=1,
            allow_delegation=False,
        )
        assert [tool.name for tool in pruned] == [other.name]

        # 父运行：描述里带上可派清单
        monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())
        injected = await _apply_delegation_policy(
            [builtin],
            agent_repo=_Repo([SimpleNamespace(slug="alpha", name="Bot-alpha")]),
            platform_id=1,
            allow_delegation=True,
        )
        assert "alpha（Bot-alpha）" in injected[0].description
        assert injected[0].name == DELEGATE_TASKS_TOOL_NAME

    asyncio.run(body())


def test_load_runtime_context_prunes_mcp_for_child_runs(monkeypatch) -> None:
    """platform_tools_only=True 时根本不查 MCP：子运行没有渠道弹确认。"""

    async def body():
        monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())
        from app.modules.conversation.runtime import load_runtime_context

        calls = {"mcp": 0}

        class _McpRepo:
            async def list_enabled_tools_for_agent(self, agent_id, platform_id):
                calls["mcp"] += 1
                return [SimpleNamespace(name="external_tool", side_effect="external")]

        class _BuiltinRepo:
            async def list_enabled_tools_for_agent(self, agent_id, platform_id):
                return [get_builtin_tool(DELEGATE_TASKS_TOOL_NAME)]

        class _AgentRepo:
            async def get_published_agent(self, agent_id, platform_id):
                return SimpleNamespace(
                    id=agent_id,
                    default_version=SimpleNamespace(id=1, version=1, model_name="m"),
                )

            async def list_published_active_agents(self, platform_id, *, limit):
                return [SimpleNamespace(slug="alpha", name="Bot-alpha")]

        class _EmptyRepo:
            async def list_enabled_for_agent(self, *args, **kwargs):
                return []

        context = await load_runtime_context(
            _AgentRepo(),
            _EmptyRepo(),
            _EmptyRepo(),
            _McpRepo(),
            _BuiltinRepo(),
            agent_id=1,
            platform_id=1,
            allow_delegation=False,
            platform_tools_only=True,
        )

        assert calls["mcp"] == 0
        assert context.mcp_tools == []
        assert context.builtin_tools == []

    asyncio.run(body())
