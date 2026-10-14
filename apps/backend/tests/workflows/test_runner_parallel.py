"""并行调度的运行期语义：真并发、汇聚等待、fail-fast、并发闸与单步超时。

与 ``test_runner.py`` 的分工：那个文件锁线性链的传值与失败策略；这个文件专门
验证「同层并发」这一新增行为——而且必须证明它**真的**在并发，不是把顺序执行
说成并行：

- 用 ``workflow_step_runs.started_at`` / ``finished_at`` 的**时间窗交叉**做证据，
  不只看替身内部的计数器；
- 用文件库而不是内存库。每个步骤各开一个 Session，内存库（StaticPool）下
  所有 Session 挤同一条 sqlite 连接，并发写会互相踩踏，测出来的「并发」不真。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.conversation.models import AgentLoopRun, Conversation
from app.modules.workflows import runner, validators
from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowStepRun
from app.shared.base_model import BaseModel
from helpers import add_published_agent, agent_step, seed


async def _make_parallel_session(path: Path):
    """建一个可并发的 sqlite 文件库（WAL + busy_timeout）。"""

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _configure(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # 并发分支会短时间争抢写锁；没有 busy_timeout 会直接报 database is locked。
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _make_workflow(session, meta, steps, **overrides) -> Workflow:
    data = {
        "platform_id": meta.platform.id,
        "name": "parallel",
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


async def _make_run(session, workflow, **overrides) -> int:
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


def _fan_out_steps(branch_count: int = 3) -> list[dict]:
    """一个入口 + N 个并行分支 + 一个显式汇聚步骤。"""

    branch_ids = [f"branch_{index}" for index in range(branch_count)]
    return [
        agent_step("entry", prompt="拆解问题"),
        *[
            agent_step(branch_id, depends_on=["entry"], prompt=f"执行 {branch_id}")
            for branch_id in branch_ids
        ],
        agent_step(
            "merge",
            depends_on=branch_ids,
            prompt="汇总 " + " / ".join(f"{{{{{b}.output}}}}" for b in branch_ids),
        ),
    ]


def _make_probe(*, delay: float = 0.05, fail_prompts: frozenset[str] = frozenset()):
    """并发探针替身：记录进出时刻、峰值并发，并可对指定提示词注入失败。"""

    probe = SimpleNamespace(calls=[], windows=[], active=0, peak=0)
    state = {"index": 0}

    async def fake_execute(session, **kwargs):
        index = state["index"]
        state["index"] += 1
        message = kwargs["message"]
        entered = time.perf_counter()
        probe.calls.append({"index": index, "message": message, "kwargs": kwargs})
        probe.active += 1
        probe.peak = max(probe.peak, probe.active)
        try:
            await asyncio.sleep(delay)
            if any(fragment in message for fragment in fail_prompts):
                raise RuntimeError(f"注入失败：{message}")
            # 每个步骤各写自己的会话与运行记录：workflow_step_runs 对两者有外键。
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
                request_id=f"parallel-test-{index}",
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
        finally:
            probe.windows.append((entered, time.perf_counter()))
            probe.active -= 1

    return probe, fake_execute


def _patch_execution(monkeypatch, fake) -> None:
    monkeypatch.setattr(runner, "execute_unattended_chat", fake)


async def _step_records(session_factory, run_id: int) -> dict[str, WorkflowStepRun]:
    async with session_factory() as session:
        records = (
            (
                await session.execute(
                    select(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
    return {record.step_id: record for record in records}


def _overlaps(left, right) -> bool:
    """两个步骤的时间窗是否交叉（真并发的直接证据）。"""

    return left.started_at < right.finished_at and right.started_at < left.finished_at


def test_parallel_branches_really_overlap_and_merge_waits(
    monkeypatch, tmp_path
) -> None:
    """验收 3：三分支真并发（时间窗交叉），汇聚在三分支终态之后才开始。"""

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "overlap.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta, _fan_out_steps())
                run_id = await _make_run(session, workflow)
                await session.commit()

            probe, fake = _make_probe(delay=0.1)
            _patch_execution(monkeypatch, fake)

            status = await runner.run_workflow_run(
                session_factory, workflow_run_id=run_id
            )
            assert status == "completed"

            # 1) 进程内证据：至少三个步骤同时在跑。
            assert probe.peak >= 3, f"峰值并发只有 {probe.peak}，分支没有同时跑"

            # 验收 8 后半：每一步都显式禁用接管，递归在 runner 侧就断掉。
            assert all(
                call["kwargs"]["allow_orchestration"] is False for call in probe.calls
            )

            # 2) 落库证据：三分支的时间窗两两交叉。
            records = await _step_records(session_factory, run_id)
            branches = [records[f"branch_{index}"] for index in range(3)]
            for index, left in enumerate(branches):
                for right in branches[index + 1 :]:
                    assert _overlaps(left, right), (
                        f"{left.step_id} 与 {right.step_id} 的时间窗不交叉："
                        f"{left.started_at}~{left.finished_at} vs "
                        f"{right.started_at}~{right.finished_at}"
                    )

            # 3) 汇聚必须等所有分支产生终态：它是下一层，不能提前开跑。
            merge = records["merge"]
            assert all(branch.finished_at <= merge.started_at for branch in branches)
            assert merge.status == "succeeded"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_parallel_branches_can_use_different_agents(monkeypatch, tmp_path) -> None:
    """验收 4：分支可指定不同 Agent，且各自用自己的 agent_id 落库。"""

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "hetero.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                extra_a = await add_published_agent(
                    session, platform_id=meta.platform.id, slug="editor"
                )
                extra_b = await add_published_agent(
                    session, platform_id=meta.platform.id, slug="critic"
                )
                steps = _fan_out_steps()
                agent_ids = {
                    "branch_0": meta.agent.id,
                    "branch_1": extra_a.id,
                    "branch_2": extra_b.id,
                }
                for step in steps:
                    if step["step_id"] in agent_ids:
                        step["agent_id"] = agent_ids[step["step_id"]]
                workflow = await _make_workflow(session, meta, steps)
                run_id = await _make_run(session, workflow)
                await session.commit()

            probe, fake = _make_probe(delay=0.02)
            _patch_execution(monkeypatch, fake)
            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "completed"
            )

            used = {call["message"]: call["kwargs"]["agent_id"] for call in probe.calls}
            for step_id, agent_id in agent_ids.items():
                assert (
                    used[f"执行 {step_id}"] == agent_id
                ), f"{step_id} 应该用 Agent {agent_id}，实际 {used[f'执行 {step_id}']}"
            # 入口与汇聚没有指定 agent_id，应回落到工作流级默认 Agent。
            assert used["拆解问题"] == meta.agent.id
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_fail_fast_finishes_started_branches_before_failing(
    monkeypatch, tmp_path
) -> None:
    """验收 5（默认档）：一个分支失败 → 整条 run failed，但同层其余分支仍有终态记录。

    关键是「先收齐再抛」：若直接取消兄弟分支，它们的步骤记录会停在 running，
    操作者既看不到真实结果，也无法判断副作用是否已发生。
    """

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "failfast.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta, _fan_out_steps())
                run_id = await _make_run(session, workflow)
                await session.commit()

            probe, fake = _make_probe(
                delay=0.05, fail_prompts=frozenset({"执行 branch_1"})
            )
            _patch_execution(monkeypatch, fake)

            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "failed"
            )

            records = await _step_records(session_factory, run_id)
            assert records["branch_1"].status == "failed"
            assert records["branch_0"].status == "succeeded"
            assert records["branch_2"].status == "succeeded"
            # 汇聚是下一层，abort 语义下不产生记录。
            assert "merge" not in records
            assert all(record.status != "running" for record in records.values())

            async with session_factory() as session:
                record = (
                    await session.execute(
                        select(WorkflowRun).where(WorkflowRun.id == run_id)
                    )
                ).scalar_one()
                assert record.status == "failed"
                # 失败前已完成的步骤要计入（入口 + 两个成功的兄弟分支），
                # 运行记录不能谎报 0。
                assert record.completed_steps == 3
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_parallel_branches_respect_concurrency_gate(monkeypatch, tmp_path) -> None:
    """单 run 内并发闸：扇出 6 条，同时在跑的步骤不超过 MAX_PARALLEL_STEPS。"""

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "gate.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(session, meta, _fan_out_steps(6))
                run_id = await _make_run(session, workflow)
                await session.commit()

            probe, fake = _make_probe(delay=0.05)
            _patch_execution(monkeypatch, fake)
            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "completed"
            )

            assert (
                probe.peak == runner.MAX_PARALLEL_STEPS
            ), f"峰值并发 {probe.peak}，期望恰好被闸在 {runner.MAX_PARALLEL_STEPS}"
            assert len(probe.calls) == 8  # 入口 + 6 分支 + 汇聚
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_continue_with_default_keeps_layer_running(monkeypatch, tmp_path) -> None:
    """验收 5（兜底档）：单分支带兜底值时 run 仍 completed，且标记 on_error_applied。"""

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "default.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                steps = _fan_out_steps()
                for step in steps:
                    if step["step_id"] == "branch_1":
                        step["on_error"] = "continue_with_default"
                        step["default_output"] = "分支不可用的兜底结论"
                workflow = await _make_workflow(session, meta, steps)
                run_id = await _make_run(session, workflow)
                await session.commit()

            probe, fake = _make_probe(
                delay=0.02, fail_prompts=frozenset({"执行 branch_1"})
            )
            _patch_execution(monkeypatch, fake)
            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "completed"
            )

            records = await _step_records(session_factory, run_id)
            # 沿用既有契约（test_runner.py 锁定）：走了兜底的那一步状态仍记 failed，
            # 靠 on_error_applied 表达「它是带着兜底值过去的」——不把失败伪装成成功。
            assert records["branch_1"].status == "failed"
            assert records["branch_1"].on_error_applied is True
            assert records["branch_1"].model_visible_output == "分支不可用的兜底结论"
            # 兜底值必须真的流进汇聚的提示词，否则「继续」只是继续了一条空链路。
            merge_prompt = next(
                call["message"] for call in probe.calls if "汇总" in call["message"]
            )
            assert "分支不可用的兜底结论" in merge_prompt
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_step_timeout_fails_only_that_step(monkeypatch, tmp_path) -> None:
    """单步超时：只有超时那一步失败，run 记 failed 且错误文案带秒数。"""

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "timeout.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                steps = _fan_out_steps()
                for step in steps:
                    if step["step_id"] == "branch_2":
                        step["timeout_seconds"] = 1
                workflow = await _make_workflow(session, meta, steps)
                run_id = await _make_run(session, workflow)
                await session.commit()

            probe, fake = _make_probe(delay=5)
            _patch_execution(monkeypatch, fake)
            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "failed"
            )

            records = await _step_records(session_factory, run_id)
            assert records["branch_2"].status == "failed"
            assert "执行超时" in (records["branch_2"].error_message or "")
            # 兄弟分支在超时判定之后仍需收尾（延迟 5s 的替身被同层闸等待）。
            assert records["branch_0"].status in {"succeeded", "failed"}
            assert all(record.status != "running" for record in records.values())
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_conversation_trigger_never_auto_approves(monkeypatch, tmp_path) -> None:
    """验收 8（审批侧）：会话内触发的运行忽略工作流自身的 auto_approve 设置。

    否则终端用户只要发一条消息，就能借工作流里预置的 auto_approve=True
    绕开人工确认执行有副作用的工具。
    """

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "policy.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                # 工作流自己声明「全部自动批准」，但触发源是会话。
                workflow = await _make_workflow(
                    session,
                    meta,
                    [agent_step("entry", prompt="做点事")],
                    auto_approve=True,
                    strict_approval=False,
                )
                run_id = await _make_run(session, workflow, trigger_kind="conversation")
                await session.commit()

            probe, fake = _make_probe(delay=0)
            _patch_execution(monkeypatch, fake)
            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "completed"
            )

            decider = probe.calls[0]["kwargs"]["confirmation_decider"]
            tool = SimpleNamespace(name="http_post", side_effect="external")
            decision = await decider(tool, None)
            assert decision.approved is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_manual_trigger_still_honours_workflow_auto_approve(
    monkeypatch, tmp_path
) -> None:
    """对照：手工触发时工作流自身的 auto_approve 仍然生效（没有把开关一起改死）。"""

    async def run() -> None:
        engine, session_factory = await _make_parallel_session(tmp_path / "manual.db")
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _make_workflow(
                    session,
                    meta,
                    [agent_step("entry", prompt="做点事")],
                    auto_approve=True,
                    strict_approval=False,
                )
                run_id = await _make_run(session, workflow, trigger_kind="manual")
                await session.commit()

            probe, fake = _make_probe(delay=0)
            _patch_execution(monkeypatch, fake)
            assert (
                await runner.run_workflow_run(session_factory, workflow_run_id=run_id)
                == "completed"
            )

            decider = probe.calls[0]["kwargs"]["confirmation_decider"]
            tool = SimpleNamespace(name="http_post", side_effect="external")
            assert (await decider(tool, None)).approved is True
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_terminal_step_id_prefers_the_only_sink() -> None:
    """汇聚步骤才是编排的对外输出；线性链的终态就是最后一步。"""

    assert runner.terminal_step_id(_fan_out_steps()) == "merge"
    assert runner.terminal_step_id([agent_step("a"), agent_step("b")]) == "b"
