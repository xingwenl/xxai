"""工作流服务层的用例（spec 验收第 2、3、4 条）。

服务层是「保存时校验」与「跨租户越权」的唯一关口：定时触发不经过 HTTP，
所以这些规则必须在这里，而不是路由层。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.tasks.unattended import NEVER_AUTO_APPROVE_SIDE_EFFECTS
from app.modules.workflows import services, validators
from app.modules.workflows.models import Workflow, WorkflowRun
from app.modules.workflows.repositories import (
    WorkflowRepository,
    WorkflowRunRepository,
    WorkflowStepRunRepository,
)
from app.modules.workflows.schemas import (
    WorkflowCreate,
    WorkflowStepInput,
    WorkflowStepRunDetail,
    WorkflowUpdate,
)
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from helpers import add_published_agent, agent_step, make_session, seed, tool_step


def _steps(*raw_steps) -> list[WorkflowStepInput]:
    return [WorkflowStepInput(**step) for step in raw_steps]


async def _created(session, meta, *, steps=None, name="测试工作流", **overrides):
    """走真实的 ``create_workflow`` 建一条工作流（默认用 ``meta`` 的已发布 Agent）。"""

    payload = WorkflowCreate(
        name=name,
        agent_id=meta.agent.id,
        steps=steps or _steps(agent_step("only")),
        **overrides,
    )
    return await services.create_workflow(
        session,
        platform_id=meta.platform.id,
        payload=payload,
        owner_user_id=meta.member.id,
        created_by_user_id=meta.member.id,
    )


def _fake_tools(monkeypatch, tools) -> None:
    """把运行期工具清单换成替身，让 ``_ensure_tool_step_available`` 的判定逻辑留在测内。"""

    async def fake_load(session, *, platform_id, agent_id, cache):
        return tools

    monkeypatch.setattr(services, "_load_agent_tools", fake_load)


def test_create_workflow_rejects_when_platform_limit_reached(monkeypatch) -> None:
    """锁（验收 2 限额）：平台工作流数量达到 ``settings.workflow_max_per_platform``
    时抛 ``ConflictException``，且不写库。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                monkeypatch.setattr(
                    services,
                    "get_settings",
                    lambda: SimpleNamespace(workflow_max_per_platform=1),
                )
                await _created(session, meta, name="第一个")

                with pytest.raises(ConflictException) as excinfo:
                    await _created(session, meta, name="第二个")
                assert "平台工作流数量已达上限（1）" in str(excinfo.value)
                assert (
                    await WorkflowRepository(session).count_for_platform(meta.platform.id)
                    == 1
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_create_workflow_rejects_agent_outside_the_platform() -> None:
    """锁（验收 4）：默认 ``agent_id`` 与步骤覆盖的 ``agent_id`` 都必须属于本平台。

    步骤级 ``agent_id`` 是跨租户越权的唯一入口：不逐个校验，A 平台的工作流
    就能驱动 B 平台的 Agent 执行。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                other = await seed(session)
                outside_agent = await add_published_agent(
                    session, platform_id=other.platform.id, slug=f"outside-{other.agent.id}"
                )
                await session.commit()
                repo = WorkflowRepository(session)

                # 工作流级默认 Agent 来自别的平台。
                with pytest.raises(BadRequestException) as excinfo:
                    await services.create_workflow(
                        session,
                        platform_id=meta.platform.id,
                        payload=WorkflowCreate(
                            name="越权",
                            agent_id=outside_agent.id,
                            steps=_steps(agent_step("only")),
                        ),
                        owner_user_id=meta.member.id,
                    )
                assert "该平台下不存在已发布的 Agent" in str(excinfo.value)

                # 步骤用 agent_id 覆盖成别的平台的 Agent。
                with pytest.raises(BadRequestException) as excinfo:
                    await services.create_workflow(
                        session,
                        platform_id=meta.platform.id,
                        payload=WorkflowCreate(
                            name="越权",
                            agent_id=meta.agent.id,
                            steps=_steps(agent_step("only", agent_id=outside_agent.id)),
                        ),
                        owner_user_id=meta.member.id,
                    )
                assert "该平台下不存在已发布的 Agent" in str(excinfo.value)
                assert await repo.count_for_platform(meta.platform.id) == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_create_workflow_rejects_an_unpublished_agent() -> None:
    """锁：本平台但**未发布**的 Agent 同样被拒（``get_published_agent`` 要求已发布版本）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session, published=False)

                with pytest.raises(BadRequestException) as excinfo:
                    await services.create_workflow(
                        session,
                        platform_id=meta.platform.id,
                        payload=WorkflowCreate(
                            name="未发布",
                            agent_id=meta.agent.id,
                            steps=_steps(agent_step("only")),
                        ),
                        owner_user_id=meta.member.id,
                    )
                assert "该平台下不存在已发布的 Agent" in str(excinfo.value)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_create_workflow_rejects_never_auto_approved_tool_step(monkeypatch) -> None:
    """锁（验收 3）：``side_effect`` 落在 ``NEVER_AUTO_APPROVE_SIDE_EFFECTS``
    的工具步骤保存时被拒，且**不写库**。

    判定依据是运行期工具清单对象的 ``side_effect`` 属性（不是直接查
    ``BuiltinToolRepository``）：``financial`` 在无人值守下永远拿不到批准，
    写进工作流等于每次运行都注定在这一步失败，而前面步骤的副作用已经发生。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                assert "financial" in NEVER_AUTO_APPROVE_SIDE_EFFECTS
                _fake_tools(
                    monkeypatch,
                    [
                        SimpleNamespace(name="orders.refund", side_effect="financial"),
                        SimpleNamespace(name="orders.get_status", side_effect="read"),
                    ],
                )

                with pytest.raises(BadRequestException) as excinfo:
                    await _created(
                        session,
                        meta,
                        steps=_steps(tool_step("refund", "orders.refund")),
                    )
                message = str(excinfo.value)
                assert "orders.refund" in message
                assert "financial" in message
                assert "不会被自动批准" in message
                assert (
                    await WorkflowRepository(session).count_for_platform(meta.platform.id)
                    == 0
                )

                # 正向对照：同一个替身清单里非禁区副作用的工具必须能存进去。
                created = await _created(
                    session,
                    meta,
                    steps=_steps(tool_step("query", "orders.get_status")),
                )
                assert created.id is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_create_workflow_rejects_unknown_tool_name(monkeypatch) -> None:
    """锁：工具名不在该 Agent 的可用清单里时，保存时就被拒（不是等到运行）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                _fake_tools(
                    monkeypatch, [SimpleNamespace(name="orders.get_status", side_effect="read")]
                )

                with pytest.raises(BadRequestException) as excinfo:
                    await _created(
                        session, meta, steps=_steps(tool_step("ghost", "orders.ghost"))
                    )
                assert "不在 Agent" in str(excinfo.value)
                assert "orders.ghost" in str(excinfo.value)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_version_increments_on_every_definition_save_only() -> None:
    """锁（ADR 的定义版本语义）：保存 ``steps`` 令 ``version`` 加一，
    只改名字/状态这类元数据时版本不动。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _created(session, meta, steps=_steps(agent_step("first")))
                assert (workflow.version, workflow.status) == (1, "active")
                assert (
                    workflow.definition["nodes"][0]["step_id"] == "first"
                )

                renamed = await services.update_workflow(
                    session,
                    workflow=workflow,
                    payload=WorkflowUpdate(name="改了名字"),
                )
                assert renamed.name == "改了名字"
                assert renamed.version == 1
                assert renamed.definition["nodes"][0]["step_id"] == "first"

                updated = await services.update_workflow(
                    session,
                    workflow=workflow,
                    payload=WorkflowUpdate(steps=_steps(agent_step("renamed"))),
                )
                assert updated.version == 2
                assert updated.definition["nodes"][0]["step_id"] == "renamed"

                paused = await services.update_workflow(
                    session, workflow=workflow, payload=WorkflowUpdate(status="paused")
                )
                assert (paused.status, paused.version) == ("paused", 2)

                again = await services.update_workflow(
                    session,
                    workflow=workflow,
                    payload=WorkflowUpdate(steps=_steps(agent_step("final"))),
                )
                assert again.version == 3
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_update_workflow_validates_step_references(monkeypatch) -> None:
    """锁：更新时同样跑 Agent / 工具校验，且校验失败不落库、不加版本。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                other = await seed(session)
                outside_agent = await add_published_agent(
                    session, platform_id=other.platform.id, slug=f"update-{other.agent.id}"
                )
                workflow = await _created(session, meta)
                await session.commit()

                with pytest.raises(BadRequestException) as excinfo:
                    await services.update_workflow(
                        session,
                        workflow=workflow,
                        payload=WorkflowUpdate(
                            steps=_steps(agent_step("only", agent_id=outside_agent.id))
                        ),
                    )
                assert "该平台下不存在已发布的 Agent" in str(excinfo.value)
                refreshed = await WorkflowRepository(session).get_scoped(
                    workflow.id, meta.platform.id
                )
                assert refreshed.version == 1
                assert refreshed.definition["nodes"][0]["step_id"] == "only"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_enqueue_manual_run_queues_then_reports_overlap() -> None:
    """锁（验收 5 + 调度器契约）：手动触发写「已排队」记录——
    ``status='running'`` 且 **``started_at`` 为空**；已有 running 时改写 skipped+overlapped。

    这里必须断言 ``started_at is None``：提前写入 ``started_at`` 会让调度器
    认为它已经在执行、永远不认领，记录就一直卡在 running 直到被看门狗判超时。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _created(session, meta, steps=_steps(agent_step("only")))

                run_row, started = await services.enqueue_manual_run(
                    session, workflow, user_id=meta.member.id, is_platform_admin=False
                )
                assert started is True
                assert run_row.status == "running"
                assert run_row.started_at is None
                assert run_row.trigger_kind == "manual"
                assert run_row.run_as_type == "user"
                assert run_row.run_as_user_id == meta.member.id
                assert run_row.planned_at is not None
                assert run_row.total_steps == 1
                assert run_row.definition_version_id == workflow.version
                assert run_row.definition_snapshot == workflow.definition

                # 「排队中」= 调度器能认领，这是 started_at 为空的直接后果。
                claimed = await WorkflowRunRepository(session).claim_queued_runs()
                assert claimed == [run_row.id]

                skipped, started_again = await services.enqueue_manual_run(
                    session, workflow, user_id=meta.member.id, is_platform_admin=False
                )
                assert started_again is False
                assert skipped.status == "skipped"
                assert skipped.skip_reason == "overlapped"
                assert skipped.trigger_kind == "manual"
                assert skipped.run_as_user_id == meta.member.id
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_assert_can_manage_uses_404_for_non_owner() -> None:
    """锁：普通用户对别人的工作流拿到 404 语义（``NotFoundException``），
    平台管理员放行；越权与「不存在」对外是同一个回答。"""

    owned = Workflow(
        platform_id=1, name="我的", agent_id=1, owner_user_id=7, definition={}
    )
    platform_level = Workflow(
        platform_id=1, name="平台级", agent_id=1, owner_user_id=None, definition={}
    )

    assert services.assert_can_manage(owned, user_id=7, is_platform_admin=False) is None
    with pytest.raises(NotFoundException) as excinfo:
        services.assert_can_manage(owned, user_id=8, is_platform_admin=False)
    assert str(excinfo.value) == "workflow not found"

    # 管理员放行：自己不是 owner、甚至是平台级（owner 为空）都能管。
    assert services.assert_can_manage(owned, user_id=8, is_platform_admin=True) is None
    assert (
        services.assert_can_manage(platform_level, user_id=8, is_platform_admin=True)
        is None
    )
    with pytest.raises(NotFoundException):
        services.assert_can_manage(platform_level, user_id=8, is_platform_admin=False)


def test_get_run_detail_returns_snapshot_and_step_outputs() -> None:
    """锁（验收 7 的读取面）：详情返回 run + 当次 ``definition_snapshot`` + 步骤明细
    （含只在详情里出现的 ``raw_output``），跨工作流的 run_id 一律 404。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _created(
                    session,
                    meta,
                    steps=_steps(agent_step("first"), agent_step("second")),
                )
                run_row, _ = await services.enqueue_manual_run(
                    session, workflow, user_id=meta.member.id, is_platform_admin=False
                )

                steps = WorkflowStepRunRepository(session)
                succeeded = await steps.create_step_run(
                    run_id=run_row.id, step_id="first", seq=0, node_type="agent"
                )
                await steps.finish_step_run(
                    succeeded,
                    status="succeeded",
                    model_visible_output="可见输出",
                    raw_output="完整未截断输出",
                    retry_count=1,
                )
                fallback = await steps.create_step_run(
                    run_id=run_row.id, step_id="second", seq=1, node_type="agent"
                )
                await steps.finish_step_run(
                    fallback,
                    status="failed",
                    model_visible_output="兜底值",
                    raw_output="兜底值",
                    error_message="模型调用失败",
                    on_error_applied=True,
                )
                await session.commit()

                detail = await services.get_run_detail(
                    session, workflow=workflow, run_id=run_row.id
                )
                assert detail.run.id == run_row.id
                assert detail.definition_snapshot == workflow.definition
                assert [step.step_id for step in detail.steps] == ["first", "second"]
                assert detail.steps[0].raw_output == "完整未截断输出"
                # 界面靠这两个「算出来的」字段显示字节数与截断提示，不能变成 undefined。
                assert detail.steps[0].raw_output_size == len(
                    "完整未截断输出".encode("utf-8")
                )
                assert detail.steps[0].output_truncated is False
                assert detail.steps[1].on_error_applied is True
                assert detail.steps[1].model_visible_output == "兜底值"

                # 别的工作流的 run_id：按「不存在」处理，避免读到不相关明细。
                other = await _created(session, meta, name="另一个")
                other.run_as_user_id = None
                other_row, _ = await services.enqueue_manual_run(
                    session, other, user_id=meta.member.id, is_platform_admin=False
                )
                with pytest.raises(NotFoundException):
                    await services.get_run_detail(
                        session, workflow=workflow, run_id=other_row.id
                    )
                with pytest.raises(NotFoundException):
                    await services.get_run_detail(
                        session, workflow=workflow, run_id=run_row.id + 100000
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_step_run_detail_marks_truncated_visible_output() -> None:
    """锁：``output_truncated`` 与写入端 ``validators.truncate_output`` 同口径。

    超过 50KB 的完整输出只留在 ``raw_output`` 里，给模型看的那一路被截断并带标记；
    界面要能据此显示「已截断 + 完整多少字节」，所以判定必须来自同一个函数，
    不能各写一份 endswith 判断。
    """

    long_text = "字" * (validators.MAX_VISIBLE_OUTPUT_BYTES // 3 + 100)
    visible = validators.truncate_output(long_text)
    assert visible != long_text and validators.is_truncated(visible)

    truncated = WorkflowStepRunDetail(
        id=1,
        run_id=1,
        step_id="first",
        seq=0,
        node_type="agent",
        status="succeeded",
        model_visible_output=visible,
        retry_count=1,
        on_error_applied=False,
        raw_output=long_text,
    )
    assert truncated.raw_output_size == len(long_text.encode("utf-8"))
    assert truncated.output_truncated is True
    # 序列化必须带上这两个字段，否则前端拿到的还是 undefined。
    dumped = truncated.model_dump()
    assert dumped["raw_output_size"] == len(long_text.encode("utf-8"))
    assert dumped["output_truncated"] is True

    empty = WorkflowStepRunDetail(
        id=2,
        run_id=1,
        step_id="second",
        seq=1,
        node_type="tool",
        status="failed",
        model_visible_output=None,
        retry_count=1,
        on_error_applied=False,
        raw_output=None,
    )
    assert empty.raw_output_size == 0
    assert empty.output_truncated is False


def test_get_workflow_or_404_is_platform_scoped() -> None:
    """锁：取工作流必须带平台范围，跨平台的 id 取不到（404 语义）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                other = await seed(session)
                workflow = await _created(session, meta)
                await session.commit()

                found = await services.get_workflow_or_404(
                    session, workflow_id=workflow.id, platform_id=meta.platform.id
                )
                assert found.id == workflow.id

                with pytest.raises(NotFoundException) as excinfo:
                    await services.get_workflow_or_404(
                        session, workflow_id=workflow.id, platform_id=other.platform.id
                    )
                assert str(excinfo.value) == "workflow not found"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_workflow_cascades_runs() -> None:
    """锁：删除定义后其运行记录按库级外键级联消失（不留下孤儿运行）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _created(session, meta)
                run_row, _ = await services.enqueue_manual_run(
                    session, workflow, user_id=meta.member.id, is_platform_admin=False
                )
                workflow_id = workflow.id
                run_id = run_row.id

                await services.delete_workflow(session, workflow=workflow)

                assert await WorkflowRepository(session).get_scoped(
                    workflow_id, meta.platform.id
                ) is None
                assert await WorkflowRunRepository(session).get_running(workflow_id) is None
                assert await session.get(WorkflowRun, run_id) is None
        finally:
            await engine.dispose()

    asyncio.run(run())
