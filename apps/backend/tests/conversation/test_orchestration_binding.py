"""编排绑定接管会话的端到端语义（spec 验收第 6、8 条）。

四件事在这里锁死：

1. **未绑定 = 零变化**。``orchestration_event_stream`` 必须返回 ``None``，调用方
   才会走回原来的 ``build_langchain_runtime``。这是「改造前行为逐字一致」的
   唯一开关，一旦这里返回了空流而不是 None，所有存量 Agent 的回复都会变成空串。
2. **绑定 = 整轮接管**。汇聚步骤的输出成为这一轮的 assistant 内容，且过程
   落在 ``workflow_runs`` / ``workflow_step_runs`` 里可回查。
3. **失败是运行结果，不是异常**。转成 ``error`` 事件，交给既有的消费分支收尾。
4. **会话触发不参与「同一工作流只能有一条 running」**。两个会话同时说话必须
   各自拿到结果，而不是互相把对方改写成 skipped。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.schemas import AgentUpdate
from app.modules.agent.services import update_agent
from app.modules.conversation.models import AgentLoopRun, Conversation
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform, PlatformAdmin
from app.modules.user.models import User
from app.modules.workflows import orchestration, runner, validators
from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowStepRun
from app.shared.base_model import BaseModel
from app.shared.exceptions import BadRequestException, NotFoundException


# --------------------------------------------------------------------------- #
# 夹具：本文件不能用 tests/workflows/helpers.py
#
# tests/conversation/ 有 __init__.py（走包导入），tests/workflows/ 没有（靠 pytest
# 把测试目录塞进 sys.path）。两边的导入方式不兼容，所以这里自带一份最小夹具。
# --------------------------------------------------------------------------- #
async def _make_session(tmp_path: Path, name: str = "orch.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")

    @event.listens_for(engine.sync_engine, "connect")
    def _configure(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session) -> SimpleNamespace:
    """平台 + 一个已发布 Agent + 管理员，够撑起编排链路。"""

    platform = Platform(name="Acme", code=f"acme-{id(session)}")
    session.add(platform)
    await session.flush()
    agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="你是测试助手",
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    admin = User(
        name="Admin", email="admin@acme.test", account="admin", password="password"
    )
    session.add(admin)
    await session.flush()
    session.add(PlatformAdmin(platform_id=platform.id, user_id=admin.id))
    await session.flush()
    # 编排运行若以终端用户身份执行，run_as_end_user_id 指向的是这张表而不是 users。
    end_user = PlatformEndUser(platform=platform, external_user_id="external_1")
    session.add(end_user)
    await session.flush()
    return SimpleNamespace(
        platform=platform,
        agent=agent,
        version=version,
        admin=admin,
        end_user=end_user,
    )


def _steps() -> list[dict]:
    """入口 → 两个并行分支 → 显式汇聚。"""

    return [
        {
            "step_id": "entry",
            "name": "拆解",
            "kind": "agent",
            "depends_on": [],
            "position": None,
            "agent_id": None,
            "prompt": "拆解问题",
            "tool_name": None,
            "tool_arguments": {},
            "input_bindings": {},
            "on_error": "abort",
            "max_retries": 0,
            "default_output": None,
            "timeout_seconds": None,
        },
        {
            "step_id": "branch_a",
            "name": "分支 A",
            "kind": "agent",
            "depends_on": ["entry"],
            "position": None,
            "agent_id": None,
            "prompt": "分支 A 的任务",
            "tool_name": None,
            "tool_arguments": {},
            "input_bindings": {},
            "on_error": "abort",
            "max_retries": 0,
            "default_output": None,
            "timeout_seconds": None,
        },
        {
            "step_id": "branch_b",
            "name": "分支 B",
            "kind": "agent",
            "depends_on": ["entry"],
            "position": None,
            "agent_id": None,
            "prompt": "分支 B 的任务",
            "tool_name": None,
            "tool_arguments": {},
            "input_bindings": {},
            "on_error": "abort",
            "max_retries": 0,
            "default_output": None,
            "timeout_seconds": None,
        },
        {
            "step_id": "merge",
            "name": "汇聚",
            "kind": "agent",
            "depends_on": ["branch_a", "branch_b"],
            "position": None,
            "agent_id": None,
            "prompt": "汇总 {{branch_a.output}} 与 {{branch_b.output}}",
            "tool_name": None,
            "tool_arguments": {},
            "input_bindings": {},
            "on_error": "abort",
            "max_retries": 0,
            "default_output": None,
            "timeout_seconds": None,
        },
    ]


async def _make_workflow(session, meta, **overrides) -> Workflow:
    data = {
        "platform_id": meta.platform.id,
        "name": "编排",
        "agent_id": meta.agent.id,
        "owner_user_id": meta.admin.id,
        "status": "active",
        "version": 1,
        "definition": validators.compile_definition(_steps()),
        "max_steps": 50,
        "timeout_seconds": 600,
        "auto_approve": True,
        "strict_approval": False,
    }
    data.update(overrides)
    workflow = Workflow(**data)
    session.add(workflow)
    await session.flush()
    return workflow


def _make_fake(*, fail_on: str | None = None, delay: float = 0.0):
    """替身：真实落 Conversation + AgentLoopRun，保证外键链完整。"""

    calls: list[dict] = []
    state = {"index": 0}

    async def fake_execute(session, **kwargs):
        index = state["index"]
        state["index"] += 1
        calls.append({"index": index, **kwargs})
        if delay:
            await asyncio.sleep(delay)
        if fail_on is not None and fail_on in kwargs["message"]:
            raise RuntimeError(f"注入失败：{kwargs['message']}")
        conversation = Conversation(
            platform_id=kwargs["platform_id"],
            agent_id=kwargs["agent_id"],
            user_id=kwargs["user_id"],
            platform_end_user_id=kwargs["end_user_id"],
            title="编排步骤",
        )
        session.add(conversation)
        await session.flush()
        loop = AgentLoopRun(
            conversation_id=conversation.id,
            request_id=f"orch-test-{index}",
            status="completed",
        )
        session.add(loop)
        await session.flush()
        content = f"输出#{index}"
        return (
            conversation,
            SimpleNamespace(id=1, content=content),
            SimpleNamespace(content=content, loop_id=loop.id),
        )

    return calls, fake_execute


def _use_test_factory(monkeypatch, session_factory) -> None:
    """把接管链路用的全局 Session 工厂换成测试库。

    ``orchestration_event_stream`` 内部调的是 ``get_session_factory()``（生产里拿到
    的是应用级引擎），测试里必须换掉——这与
    ``apps/backend/tests/gateway/test_stream_session_teardown.py:54`` 的做法一致。
    不换的话，编排会在应用级引擎上找到另一个测试留下的同号工作流，测出来的东西
    与被测对象无关。
    """

    monkeypatch.setattr(
        "app.modules.conversation.services.get_session_factory",
        lambda: session_factory,
    )


# --------------------------------------------------------------------------- #
# 纯函数：绑定判定与上下文打包
# --------------------------------------------------------------------------- #
def test_orchestration_workflow_id_reads_the_agent_binding() -> None:
    assert (
        orchestration.orchestration_workflow_id(
            SimpleNamespace(agent=SimpleNamespace(id=1, orchestration_workflow_id=7))
        )
        == 7
    )
    assert (
        orchestration.orchestration_workflow_id(
            SimpleNamespace(agent=SimpleNamespace(id=1, orchestration_workflow_id=None))
        )
        is None
    )


def test_build_turn_prefix_carries_history_and_current_message() -> None:
    prefix = orchestration.build_turn_prefix(
        [
            SimpleNamespace(role="user", content="第一句"),
            SimpleNamespace(role="assistant", content="第一句的回答"),
            SimpleNamespace(role="tool", content="工具原始输出不该进提示词"),
        ],
        "第二句",
    )
    assert "第一句" in prefix
    assert "第一句的回答" in prefix
    assert "第二句" in prefix
    # 工具消息是内部执行痕迹，不是对话上下文。
    assert "工具原始输出不该进提示词" not in prefix
    # 没有历史时必须给占位，不能留一个空标题让模型以为上下文丢了。
    assert "（没有更早的历史）" in orchestration.build_turn_prefix([], "只有这一句")


def test_build_turn_prefix_accepts_orm_langchain_and_dict_shapes() -> None:
    """三种历史形状都要能吃下：REST 侧传 ORM 对象，Embed 侧传 langchain 消息。"""

    class HumanMessage:  # 只按类名判断，编排模块刻意不 import langchain
        def __init__(self, content):
            self.content = content

    prefix = orchestration.build_turn_prefix(
        [
            HumanMessage("问句"),
            SimpleNamespace(role="assistant", content=[{"text": "分片回答"}]),
            {"role": "user", "content": "字典问句"},
            # 裸字符串没有角色，无法归属到谁说的，只能丢弃——比猜错角色安全。
            "裸字符串",
        ],
        "当前",
    )
    assert "问句" in prefix
    assert "分片回答" in prefix
    assert "字典问句" in prefix
    assert "裸字符串" not in prefix


# --------------------------------------------------------------------------- #
# 开关：未绑定 / 显式禁用一律不接管
# --------------------------------------------------------------------------- #
def test_unbound_agent_yields_no_orchestration_stream() -> None:
    """验收 6 后半：未绑定的 Agent 必须拿到 None，才能走回原来的模型链路。"""

    stream = orchestration_stream_for(binding=None)
    assert stream is None


def test_allow_orchestration_false_never_takes_over() -> None:
    """验收 8 后半：工作流 Agent 步骤显式禁用接管——否则会无限递归。

    ``_run_agent_step`` 内部就在跑编排，若这一步的 Agent 又绑定工作流并被允许
    接管，就是「编排调用编排」的自指。
    """

    assert orchestration_stream_for(binding=7, allow_orchestration=False) is None


def orchestration_stream_for(*, binding: int | None, allow_orchestration: bool = True):
    """调 ``orchestration_event_stream``，只关心「有没有流」。"""

    from app.modules.conversation.services import orchestration_event_stream

    return orchestration_event_stream(
        SimpleNamespace(agent=SimpleNamespace(id=1, orchestration_workflow_id=binding)),
        history=[],
        message="你好",
        platform_id=1,
        user_id=1,
        end_user_id=None,
        allow_orchestration=allow_orchestration,
    )


# --------------------------------------------------------------------------- #
# 端到端：接管一轮
# --------------------------------------------------------------------------- #
def test_bound_agent_takes_over_the_turn_and_records_the_run(
    monkeypatch, tmp_path
) -> None:
    """验收 6：一条消息 → 编排跑完 → 汇聚输出落库并可回查。"""

    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path)
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                workflow = await _make_workflow(session, meta)
                workflow_id = workflow.id
                await session.commit()

            calls, fake = _make_fake()
            monkeypatch.setattr(runner, "execute_unattended_chat", fake)
            _use_test_factory(monkeypatch, session_factory)

            from app.modules.conversation.services import orchestration_event_stream

            context = SimpleNamespace(
                agent=SimpleNamespace(
                    id=meta.agent.id, orchestration_workflow_id=workflow_id
                )
            )
            stream = orchestration_event_stream(
                context,
                history=[SimpleNamespace(role="user", content="上一句")],
                message="本轮问题",
                platform_id=meta.platform.id,
                user_id=None,
                end_user_id=meta.end_user.id,
                allow_orchestration=True,
            )
            assert stream is not None
            events = [event async for event in stream]

            # 事件形状与单 Agent 链路同形：一条增量 + 一条完成，内容一致。
            assert [event.type for event in events] == ["message_delta", "completed"]
            # 汇聚是最后执行的一步（第 4 次调用），它的输出就是这一轮的回复。
            assert events[0].payload["content"] == "输出#3"
            assert events[0].payload["content"] == events[1].payload["content"]
            assert events[0].payload["workflow_run_id"] == (
                events[1].payload["workflow_run_id"]
            )

            # 入口层带着会话历史，分支层不带（分支只拿自己的任务提示词）。
            entry_call = next(c for c in calls if "拆解问题" in c["message"])
            assert "上一句" in entry_call["message"]
            branch_call = next(c for c in calls if "分支 A 的任务" in c["message"])
            assert "上一句" not in branch_call["message"]

            # 每个分支显式禁用接管，递归在这里断掉。
            assert all(call["allow_orchestration"] is False for call in calls)

            async with session_factory() as session:
                run_record = (
                    await session.execute(
                        select(WorkflowRun).where(
                            WorkflowRun.workflow_id == workflow_id
                        )
                    )
                ).scalar_one()
                assert run_record.trigger_kind == "conversation"
                assert run_record.status == "completed"
                assert run_record.run_as_type == "end_user"
                assert run_record.run_as_end_user_id == meta.end_user.id
                assert run_record.completed_steps == 4

                step_records = (
                    (
                        await session.execute(
                            select(WorkflowStepRun)
                            .where(WorkflowStepRun.run_id == run_record.id)
                            .order_by(WorkflowStepRun.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [record.step_id for record in step_records] == [
                    "entry",
                    "branch_a",
                    "branch_b",
                    "merge",
                ]
                # 每步都有自己的会话与 Agent 运行记录，可回查。
                assert all(
                    record.conversation_id is not None for record in step_records
                )
                assert all(
                    record.agent_loop_run_id is not None for record in step_records
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_orchestration_failure_becomes_an_error_event(monkeypatch, tmp_path) -> None:
    """失败必须转成 ``error`` 事件：SSE 入口把抛出的异常当成连接错误。"""

    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path, "fail.db")
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                workflow = await _make_workflow(session, meta)
                workflow_id = workflow.id
                await session.commit()

            _, fake = _make_fake(fail_on="分支 B 的任务")
            monkeypatch.setattr(runner, "execute_unattended_chat", fake)
            _use_test_factory(monkeypatch, session_factory)

            from app.modules.conversation.services import orchestration_event_stream

            context = SimpleNamespace(
                agent=SimpleNamespace(
                    id=meta.agent.id, orchestration_workflow_id=workflow_id
                )
            )
            stream = orchestration_event_stream(
                context,
                history=[],
                message="本轮问题",
                platform_id=meta.platform.id,
                user_id=meta.admin.id,
                end_user_id=None,
                allow_orchestration=True,
            )
            events = [event async for event in stream]

            assert [event.type for event in events] == ["error"]
            assert events[0].payload["code"] == "orchestration_failed"
            assert "注入失败" in events[0].payload["message"]
            assert events[0].payload["retryable"] is False

            # 失败也要留痕：运行记录是 failed，而不是停在 running 让看门狗去猜。
            async with session_factory() as session:
                run_record = (
                    await session.execute(
                        select(WorkflowRun).where(
                            WorkflowRun.workflow_id == workflow_id
                        )
                    )
                ).scalar_one()
                assert run_record.status == "failed"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_same_workflow_can_run_concurrently_from_two_conversations(
    monkeypatch, tmp_path
) -> None:
    """验收 8 前半：同一工作流被两个会话同时触发，两条运行并存、都跑完。

    旧的 ``uq_workflow_runs_one_running_per_workflow`` 谓词只管
    ``status='running'``，第二条会被改写成 skipped（或者直接撞唯一索引）。
    """

    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path, "concurrent.db")
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                workflow = await _make_workflow(session, meta)
                workflow_id = workflow.id
                await session.commit()

            _, fake = _make_fake(delay=0.1)
            monkeypatch.setattr(runner, "execute_unattended_chat", fake)

            common = {
                "platform_id": meta.platform.id,
                "agent_id": meta.agent.id,
                "workflow_id": workflow_id,
                "run_as_type": "end_user",
                "user_id": None,
                "end_user_id": meta.end_user.id,
                "turn_prefix": "【本轮用户消息】\n你好",
            }
            first, second = await asyncio.gather(
                orchestration.run_orchestration_turn(session_factory, **common),
                orchestration.run_orchestration_turn(session_factory, **common),
            )

            assert first[0]
            assert second[0]
            assert first[1] != second[1]

            async with session_factory() as session:
                runs = (
                    (
                        await session.execute(
                            select(WorkflowRun).where(
                                WorkflowRun.workflow_id == workflow_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(runs) == 2
                assert all(run.trigger_kind == "conversation" for run in runs)
                assert all(run.status == "completed" for run in runs)
        finally:
            await engine.dispose()

    asyncio.run(run())


# --------------------------------------------------------------------------- #
# 绑定校验：必须是同平台的启用态工作流
# --------------------------------------------------------------------------- #
def test_update_agent_rejects_workflow_from_another_platform(tmp_path) -> None:
    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path, "cross.db")
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                other = Platform(name="Other", code="other")
                session.add(other)
                await session.flush()
                # 借另一个平台的 Agent 建出该平台的工作流。
                foreign_agent = Agent(platform_id=other.id, name="Other", slug="other")
                session.add(foreign_agent)
                await session.flush()
                foreign_workflow = Workflow(
                    platform_id=other.id,
                    name="别人的编排",
                    agent_id=foreign_agent.id,
                    owner_user_id=None,
                    status="active",
                    version=1,
                    definition=validators.compile_definition(_steps()),
                    max_steps=50,
                    timeout_seconds=600,
                    auto_approve=False,
                    strict_approval=False,
                )
                session.add(foreign_workflow)
                await session.flush()

                repo = AgentRepository(session)
                try:
                    await update_agent(
                        repo,
                        meta.agent.id,
                        AgentUpdate(orchestration_workflow_id=foreign_workflow.id),
                        platform_id=meta.platform.id,
                    )
                except NotFoundException as error:
                    assert "orchestration workflow not found" in str(error)
                else:  # pragma: no cover - 绑定成功就是越权
                    raise AssertionError("跨平台绑定必须被拒绝")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_update_agent_rejects_paused_workflow(tmp_path) -> None:
    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path, "paused.db")
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                workflow = await _make_workflow(session, meta, status="paused")
                repo = AgentRepository(session)
                try:
                    await update_agent(
                        repo,
                        meta.agent.id,
                        AgentUpdate(orchestration_workflow_id=workflow.id),
                        platform_id=meta.platform.id,
                    )
                except BadRequestException as error:
                    assert "orchestration workflow is paused" in str(error)
                else:  # pragma: no cover - 暂停的工作流接管只会让用户收到失败
                    raise AssertionError("暂停的工作流不允许绑定")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_update_agent_binds_then_unbinds(tmp_path) -> None:
    """显式传 null = 解绑；不传字段 = 不改动。"""

    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path, "bind.db")
        try:
            async with session_factory() as session:
                meta = await _seed(session)
                workflow = await _make_workflow(session, meta)
                repo = AgentRepository(session)

                bound = await update_agent(
                    repo,
                    meta.agent.id,
                    AgentUpdate(orchestration_workflow_id=workflow.id),
                    platform_id=meta.platform.id,
                )
                assert bound.orchestration_workflow_id == workflow.id

                # 只改名字：绑定不能被顺手清掉。
                renamed = await update_agent(
                    repo,
                    meta.agent.id,
                    AgentUpdate(name="改名了"),
                    platform_id=meta.platform.id,
                )
                assert renamed.orchestration_workflow_id == workflow.id

                unbound = await update_agent(
                    repo,
                    meta.agent.id,
                    AgentUpdate(orchestration_workflow_id=None),
                    platform_id=meta.platform.id,
                )
                assert unbound.orchestration_workflow_id is None
        finally:
            await engine.dispose()

    asyncio.run(run())
