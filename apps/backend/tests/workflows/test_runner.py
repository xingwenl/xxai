"""工作流执行引擎的用例（spec 验收第 5、6、7、8 条）。

不碰真实模型：把 ``execute_unattended_chat`` 换成替身（``runner`` 模块属性直接
绑定，所以 patch 目标就是 ``app.modules.workflows.runner.execute_unattended_chat``），
替身按调用次序返回不同内容并记录每次收到的 prompt，这样「上一步输出是否真的
替换进了下一步提示词」才是被断言的事实，而不是靠推断。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from app.modules.conversation.models import AgentLoopRun, Conversation
from app.modules.workflows import runner, validators
from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowStepRun
from helpers import agent_step, make_session, seed


async def _make_workflow(session, meta, steps, **overrides):
    """直接落一条工作流定义（runner 只认 ``definition_snapshot``，不重跑保存期校验）。"""

    data = {
        "platform_id": meta.platform.id,
        "name": "runner",
        "agent_id": meta.agent.id,
        "owner_user_id": meta.member.id,
        "status": "active",
        "version": 1,
        "definition": validators.compile_definition(steps),
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


async def _make_run(session, workflow, **overrides):
    """建一条 running 运行记录，默认快照取工作流当时的定义。"""

    data = {
        "workflow_id": workflow.id,
        "definition_version_id": workflow.version,
        "definition_snapshot": workflow.definition,
        "status": "running",
        "trigger_kind": "manual",
        "run_as_type": "user",
        "run_as_user_id": workflow.owner_user_id,
        "total_steps": len((workflow.definition or {}).get("nodes") or []),
    }
    data.update(overrides)
    run = WorkflowRun(**data)
    session.add(run)
    await session.flush()
    return run.id


def _make_fake(responses, calls):
    """按调用次序返回替身；``responses`` 里的 Exception 会被抛出。

    每次调用都真实写 Conversation 与 AgentLoopRun：``workflow_step_runs`` 对
    两者有外键约束，引擎回写的 id 必须真实存在。
    """

    state = {"index": 0}

    async def fake_execute(session, **kwargs):
        calls.append(kwargs)
        item = responses[state["index"]]
        state["index"] += 1
        if isinstance(item, Exception):
            raise item
        conversation = Conversation(
            platform_id=kwargs["platform_id"],
            agent_id=kwargs["agent_id"],
            user_id=kwargs["user_id"],
            platform_end_user_id=kwargs["end_user_id"],
            title="工作流步骤",
        )
        session.add(conversation)
        await session.flush()
        loop = AgentLoopRun(
            conversation_id=conversation.id,
            request_id=f"workflow-test-{state['index']}",
            status="completed",
        )
        session.add(loop)
        await session.flush()
        return (
            conversation,
            SimpleNamespace(id=1, content=item),
            SimpleNamespace(content=item, loop_id=loop.id),
        )

    return fake_execute


def _patch_execution(monkeypatch, fake) -> None:
    monkeypatch.setattr(runner, "execute_unattended_chat", fake)


def test_runner_completes_two_agent_steps_and_pipes_output(monkeypatch) -> None:
    """锁（验收 5）：两步都是 agent 步骤时，run 收尾 completed、completed_steps=2、
    两条步骤记录都 succeeded，且**第二步替身收到的 prompt 里已经嵌入了第一步的输出**。

    数据传递是编排的核心收益：只断言「两步都跑了」而不看 prompt，等于没测替换。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session,
                    meta,
                    [
                        agent_step("first", prompt="第一步"),
                        agent_step("second", prompt="拿到 {{first.output}} 继续"),
                    ],
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            calls: list[dict] = []
            _patch_execution(
                monkeypatch, _make_fake(["第一段输出", "第二段输出"], calls)
            )
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "completed"
            assert len(calls) == 2
            assert calls[0]["message"] == "第一步"
            # 上一步输出是 model_visible_output（截断后）的值，这里未截断，原样嵌入。
            assert calls[1]["message"] == "拿到 第一段输出 继续"

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.status == "completed"
                assert record.completed_steps == 2
                assert record.finished_at is not None
                assert record.error_message is None

                steps = (
                    (
                        await session.execute(
                            select(WorkflowStepRun)
                            .where(WorkflowStepRun.run_id == run_id)
                            .order_by(WorkflowStepRun.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [step.step_id for step in steps] == ["first", "second"]
                assert [step.status for step in steps] == ["succeeded", "succeeded"]
                assert [step.model_visible_output for step in steps] == [
                    "第一段输出",
                    "第二段输出",
                ]
                assert steps[0].conversation_id is not None
                assert steps[0].agent_loop_run_id is not None
                assert steps[0].raw_output == "第一段输出"
                assert steps[0].retry_count == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_aborts_remaining_steps_on_error(monkeypatch) -> None:
    """锁（验收 6）：``on_error=abort`` 时后续步骤**不执行**且**不产生记录**，
    run 记为 failed。

    不产生记录是硬要求：留一条 running 的步骤记录会让界面永远显示「卡在那一步」。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session,
                    meta,
                    [
                        agent_step("first", prompt="会失败", on_error="abort"),
                        agent_step("second", prompt="不该跑到这里"),
                    ],
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            calls: list[dict] = []
            _patch_execution(
                monkeypatch,
                _make_fake([RuntimeError("模型炸了"), "永远不该返回"], calls),
            )
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "failed"
            assert len(calls) == 1

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.status == "failed"
                assert "执行失败" in record.error_message
                assert "first" in record.error_message
                assert record.finished_at is not None

                steps = (
                    (
                        await session.execute(
                            select(WorkflowStepRun).where(
                                WorkflowStepRun.run_id == run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [step.step_id for step in steps] == ["first"]
                assert steps[0].status == "failed"
                assert "RuntimeError" in steps[0].error_message
                assert "模型炸了" in steps[0].error_message
                assert steps[0].on_error_applied is False
                assert steps[0].finished_at is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_continues_with_default_and_marks_the_step(monkeypatch) -> None:
    """锁（验收 6）：``on_error=continue_with_default`` 时后续步骤照跑，
    且失败那步的 ``on_error_applied`` 为真、输出即兜底值，下一步能引用到它。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session,
                    meta,
                    [
                        agent_step(
                            "first",
                            prompt="会失败",
                            on_error="continue_with_default",
                            default_output="兜底值",
                        ),
                        agent_step("second", prompt="用 {{first.output}}"),
                    ],
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            calls: list[dict] = []
            _patch_execution(
                monkeypatch, _make_fake([RuntimeError("模型炸了"), "第二步结果"], calls)
            )
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "completed"
            assert len(calls) == 2
            assert calls[1]["message"] == "用 兜底值"

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.status == "completed"
                # 带兜底值过去的步骤也算「完成」，否则运行进度会与实际不符。
                assert record.completed_steps == 2

                steps = (
                    (
                        await session.execute(
                            select(WorkflowStepRun)
                            .where(WorkflowStepRun.run_id == run_id)
                            .order_by(WorkflowStepRun.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [step.status for step in steps] == ["failed", "succeeded"]
                # 关键：能指出「哪一步用了兜底值」。
                assert steps[0].on_error_applied is True
                assert steps[0].model_visible_output == "兜底值"
                assert steps[0].raw_output == "兜底值"
                assert "模型炸了" in steps[0].error_message
                assert steps[1].on_error_applied is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_truncates_visible_output_but_keeps_raw(monkeypatch) -> None:
    """锁（验收 5 截断部分）：超过 50KB 的输出，``model_visible_output`` 被截断并带标记，
    ``raw_output`` 保留全量。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session, meta, [agent_step("only", prompt="大输出")]
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            big = "A" * (60 * 1024)
            calls: list[dict] = []
            _patch_execution(monkeypatch, _make_fake([big], calls))
            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "completed"
            )

            async with session_factory() as session:
                step = (
                    await session.execute(
                        select(WorkflowStepRun).where(
                            WorkflowStepRun.run_id == run_id
                        )
                    )
                ).scalar_one()
                assert step.status == "succeeded"
                assert step.raw_output == big
                assert step.model_visible_output != big
                assert validators.is_truncated(step.model_visible_output) is True
                assert step.model_visible_output.endswith(validators.TRUNCATION_MARKER)
                # 可见通道 = 前 50KB 字节 + 标记，落在「上限 + 标记」之内。
                assert step.model_visible_output == (
                    "A" * validators.MAX_VISIBLE_OUTPUT_BYTES
                    + validators.TRUNCATION_MARKER
                )
                assert len(step.model_visible_output.encode("utf-8")) <= (
                    validators.MAX_VISIBLE_OUTPUT_BYTES
                    + len(validators.TRUNCATION_MARKER.encode("utf-8"))
                )
                # 完整通道没有被压。
                assert len(step.raw_output.encode("utf-8")) == 60 * 1024
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_run_snapshot_is_immune_to_later_definition_edits(monkeypatch) -> None:
    """锁（验收 7）：运行记录持有当次定义的整份快照，事后改 ``workflow.definition``
    不会改变旧 run 的解释；下一次运行才用新定义（每次保存 version+1）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session, meta, [agent_step("first", prompt="旧定义")]
                )
                first_run_id = await _make_run(session, workflow)
                await session.commit()

            calls: list[dict] = []
            _patch_execution(monkeypatch, _make_fake(["第一版输出"], calls))
            assert (
                await runner.run_workflow_run(
                    session_factory, workflow_run_id=first_run_id
                )
                == "completed"
            )

            # 事后把定义整份换掉并加版本（模拟「保存」）。
            async with session_factory() as session:
                workflow = await session.get(Workflow, workflow.id)
                workflow.definition = validators.compile_definition(
                    [agent_step("renamed", prompt="新定义")]
                )
                workflow.version = 2
                await session.commit()

            async with session_factory() as session:
                old_run = await session.get(WorkflowRun, first_run_id)
                # 旧 run 的快照仍是旧定义，且能被完整解释。
                assert old_run.definition_version_id == 1
                assert old_run.definition_snapshot["nodes"][0]["step_id"] == "first"
                assert old_run.definition_snapshot["nodes"][0]["prompt"] == "旧定义"
                assert len(old_run.definition_snapshot["nodes"]) == 1
                assert old_run.definition_snapshot["edges"] == []

                # 新 run 才吃到新定义。
                workflow = await session.get(Workflow, old_run.workflow_id)
                second_run_id = await _make_run(session, workflow)
                await session.commit()
                new_run = await session.get(WorkflowRun, second_run_id)
                assert new_run.definition_version_id == 2
                assert new_run.definition_snapshot["nodes"][0]["step_id"] == "renamed"

                first_step = (
                    await session.execute(
                        select(WorkflowStepRun).where(
                            WorkflowStepRun.run_id == first_run_id
                        )
                    )
                ).scalar_one()
                assert first_step.step_id == "first"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_skips_paused_workflow_without_calling_model(monkeypatch) -> None:
    """锁：排队期间工作流被暂停时，runner 自己兜底记为 skipped+workflow_paused，
    并且完全不发起模型调用。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session, meta, [agent_step("only")], status="paused"
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            async def should_not_run(session, **kwargs):
                raise AssertionError("暂停的工作流不应发起模型调用")

            _patch_execution(monkeypatch, should_not_run)
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "skipped"

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.status == "skipped"
                assert record.skip_reason == "workflow_paused"
                assert "工作流已暂停" in record.error_message
                assert record.finished_at is not None
                assert (
                    await session.execute(
                        select(WorkflowStepRun).where(
                            WorkflowStepRun.run_id == run_id
                        )
                    )
                ).scalars().all() == []
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_fails_without_execution_identity(monkeypatch) -> None:
    """锁：``run_as_type='user'`` 但 ``run_as_user_id`` 为空时记为 failed，
    且一次模型调用都不发（无身份的运行会污染会话与审计）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta, [agent_step("only")])
                run_id = await _make_run(session, workflow, run_as_user_id=None)
                await session.commit()

            async def should_not_run(session, **kwargs):
                raise AssertionError("无执行身份不应发起模型调用")

            _patch_execution(monkeypatch, should_not_run)
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "failed"

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.status == "failed"
                assert "执行身份" in record.error_message
                assert record.finished_at is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_does_not_reexecute_finished_run(monkeypatch) -> None:
    """锁：已是终态的 run 不会被再次执行（看门狗标失败后不应复活）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta, [agent_step("only")])
                run_id = await _make_run(
                    session,
                    workflow,
                    status="failed",
                    error_message="已被看门狗标记",
                )
                await session.commit()

            async def should_not_run(session, **kwargs):
                raise AssertionError("终态运行不应被重新执行")

            _patch_execution(monkeypatch, should_not_run)
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "failed"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_retries_step_with_the_same_input(monkeypatch) -> None:
    """锁（Q6 每步最大重试）：``max_retries=2`` 且首跑失败、重试成功时，
    步骤记为 succeeded，``retry_count`` 记成功那次的尝试序号（2），
    且第二次尝试拿到的是**同一份输入**（重试不是换新输入）。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session,
                    meta,
                    [agent_step("first", prompt="第一步", max_retries=2)],
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            calls: list[dict] = []
            _patch_execution(
                monkeypatch,
                _make_fake([RuntimeError("第一次炸了"), "重试成功"], calls),
            )
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "completed"
            # 同一逻辑步骤被真正调了两次。
            assert len(calls) == 2
            assert [call["message"] for call in calls] == ["第一步", "第一步"]

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.status == "completed"
                assert record.completed_steps == 1

                step = (
                    await session.execute(
                        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id)
                    )
                ).scalar_one()
                assert step.status == "succeeded"
                assert step.retry_count == 2
                assert step.model_visible_output == "重试成功"
                assert step.error_message is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_exhausts_retries_before_applying_on_error(monkeypatch) -> None:
    """锁（Q6 重试与 on_error 的顺序）：重试用尽之前兜底值不得生效。

    ``max_retries=1`` 表示总共两次尝试；两次都失败后才按
    ``continue_with_default`` 继续，且 ``retry_count`` 记满尝试总数。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session,
                    meta,
                    [
                        agent_step(
                            "first",
                            prompt="会失败",
                            max_retries=1,
                            on_error="continue_with_default",
                            default_output="兜底值",
                        ),
                        agent_step("second", prompt="用 {{first.output}}"),
                    ],
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            calls: list[dict] = []
            _patch_execution(
                monkeypatch,
                _make_fake(
                    [RuntimeError("第一次炸"), RuntimeError("第二次也炸"), "第二步结果"],
                    calls,
                ),
            )
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "completed"
            # 失败那步被调两次，第三步（第二个逻辑步骤）才拿到兜底值。
            assert len(calls) == 3
            assert calls[2]["message"] == "用 兜底值"

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.completed_steps == 2

                steps = (
                    (
                        await session.execute(
                            select(WorkflowStepRun)
                            .where(WorkflowStepRun.run_id == run_id)
                            .order_by(WorkflowStepRun.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [step.status for step in steps] == ["failed", "succeeded"]
                assert steps[0].retry_count == 2
                assert steps[0].on_error_applied is True
                assert steps[0].model_visible_output == "兜底值"
                # 兜底值生效时 run 不该被标失败：错误信息只落在步骤上。
                assert record.error_message is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_runner_reports_retry_count_when_all_attempts_fail(monkeypatch) -> None:
    """锁：``on_error=abort`` 且重试用尽时，run 失败、该步失败且
    ``retry_count`` 等于尝试总数，后续步骤一条都不执行。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session,
                    meta,
                    [
                        agent_step("first", prompt="会失败", max_retries=2),
                        agent_step("second", prompt="不该跑到"),
                    ],
                )
                run_id = await _make_run(session, workflow)
                await session.commit()

            calls: list[dict] = []
            _patch_execution(
                monkeypatch,
                _make_fake(
                    [
                        RuntimeError("一"),
                        RuntimeError("二"),
                        RuntimeError("三"),
                        "不该出现",
                    ],
                    calls,
                ),
            )
            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "failed"
            assert len(calls) == 3
            assert all(call["message"] == "会失败" for call in calls)

            async with session_factory() as session:
                record = await session.get(WorkflowRun, run_id)
                assert record.status == "failed"
                assert "步骤 'first' 失败" in record.error_message

                steps = (
                    (
                        await session.execute(
                            select(WorkflowStepRun)
                            .where(WorkflowStepRun.run_id == run_id)
                            .order_by(WorkflowStepRun.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [step.status for step in steps] == ["failed"]
                assert steps[0].retry_count == 3
                assert "三" in steps[0].error_message
        finally:
            await engine.dispose()

    asyncio.run(run())
