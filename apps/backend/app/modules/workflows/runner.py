"""工作流执行引擎：把一次工作流运行按拓扑顺序跑完。

与 ``app/modules/tasks/runner.py`` 是同一族代码，差别只在「一轮」变成了
「一串步骤」，而且这串步骤是一张 **DAG**：

- **按拓扑分层**。执行顺序由 ``depends_on`` 决定，``validators.execution_layers``
  把它分成若干层；同层步骤互不依赖，可同时执行，跨层必须等待。
- **每步独立会话**。Agent 步骤调 ``execute_unattended_chat``，它每次都以
  ``conversation_id=None`` 新建会话，因此每步天然拥有独立上下文——这正是
  多步编排相对「一条长提示词」的核心收益，不需要额外的隔离机制。
- **每步独立 Session**。会话与工具执行分属两个 Session（与任务执行同一模式），
  否则模型循环跑在独立 Task 中会触发并发状态错误。
- **每步落库**。步骤开始时先写一条 ``running`` 记录并提交，界面因此能看到
  「卡在哪一步」；结束时补写状态与双通道输出。
- **失败按步骤策略处理**。``abort`` 中止整条流程并让后续步骤**不产生记录**；
  ``continue_with_default`` 用兜底值继续，但把 ``on_error_applied`` 置真，
  让运行记录如实反映「这一步是带着兜底值过去的」。
- **失败默认 fail-fast，但会先等同层已启动的分支收尾**。直接取消会让已发生的
  工具副作用处于不确定状态，也会让步骤记录停在 running；收齐再抛才可复现。
  这与 GitHub Actions 的 ``fail-fast``、Temporal 的 ``Promise.all``、
  n8n 的 ``On Error=Stop`` 是同一口径：部分失败要继续必须显式声明。

失败策略做在步骤属性上而不是流程级，是调研 Dify / n8n / GitHub Actions 后的
共同结论：只有步骤级才能表达「这一步失败可以兜底，那一步失败必须停」。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.agent.repositories import AgentRepository
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.conversation.runtime import load_runtime_context
from app.modules.conversation.services import (
    build_runtime_tool_list,
    execute_unattended_chat,
)
from app.modules.conversation.tool_dispatch import build_tool_invoker
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.repositories import McpRepository
from app.modules.skill.repositories import SkillRepository
from app.modules.tasks.unattended import UnattendedPolicy, build_confirmation_decider
from app.modules.workflows import validators
from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowStepRun
from app.modules.workflows.repositories import (
    WorkflowRunRepository,
    WorkflowStepRunRepository,
)
from app.shared.exceptions import BadRequestException

logger = logging.getLogger(__name__)

# 步骤唯一对外发布的输出名。约束成单一取值，是为了让「引用一个不存在的输出」
# 在运行时立刻失败，而不是静默替换成空字符串；取值本身与保存期校验共用
# validators.OUTPUT_PATH，避免两处口径漂移。
OUTPUT_PATH = validators.OUTPUT_PATH

# 一条 run 内部同时执行的步骤数上限（分支并发闸）。
# 与 tasks/scheduler.py 的 MAX_CONCURRENT_RUNS 正交：那个限的是「同时有几条 run」，
# 这个限的是「一条 run 里有几步在并发」。两者都要有，否则 N 条 run × M 个分支
# 会瞬间打出 N×M 个模型请求。默认 4 同时对齐了本机 Pi 的 MAX_CONCURRENCY = 4。
MAX_PARALLEL_STEPS = 4

# 步骤被跳过的原因文案。跳过是「依赖的出口都没到达」这一正常结果，不是错误；
# 但运行记录里只有 error_message 一列能携带自由文本，所以原因写在这里，
# 前端才有东西可显示（否则用户只看到一个没有解释的灰节点）。
SKIPPED_MESSAGE = "依赖的出口均未到达，本步骤被跳过"


class StepFailedError(Exception):
    """单步执行失败；消息会原样进入步骤运行记录，供排障。"""


@dataclass
class ExecutionTally:
    """一次运行的累计计数。

    不把 ``UnattendedPolicy`` 实例直接共享给并发分支：policy 的
    ``approved_count`` / ``decisions`` 是普通实例属性，跨协程共享一份实例时
    「哪些批准属于哪一步」无从区分。改为每个分支用自己的 policy，计数回传
    到这里汇总——汇总只发生在主协程里，因此不需要锁。
    """

    completed_steps: int = 0
    auto_approved_count: int = 0


@dataclass
class _StepOutcome:
    """单步结果：进 ``outputs`` 的可见输出 + 是否算作已完成 + 到达的出口。

    ``handle`` 是本步**实际走到**的出口（``validators.DEFAULT_HANDLE`` /
    ``FAILED_HANDLE`` / 条件步骤的分支名）：下游步骤能不能执行，取决于它声明的
    依赖边是否落在上游已经到达的出口里。
    """

    visible: str
    completed: bool
    handle: str


async def run_workflow_run(
    session_factory: async_sessionmaker[AsyncSession], *, workflow_run_id: int
) -> str:
    """执行一次工作流运行，返回最终状态字符串。

    返回 ``"missing"`` 表示运行记录不存在，``"running"`` 之外的既有状态表示
    这次调用不该重复执行（与任务执行保持同一套幂等口径）。
    """

    async with session_factory() as session:
        run = await session.get(WorkflowRun, workflow_run_id)
        if run is None:
            return "missing"
        if run.status != "running":
            return run.status

        workflow = await session.get(Workflow, run.workflow_id)
        if workflow is None:
            run_repo = WorkflowRunRepository(session)
            await run_repo.finish_run(
                run, status="failed", error_message="工作流已被删除"
            )
            await session.commit()
            return "failed"

        # 把需要的 ORM 字段拷到局部变量：下面会分多个 Session 长时间执行，
        # 不能依赖这个 Session 一直开着。
        platform_id = workflow.platform_id
        default_agent_id = workflow.agent_id
        max_steps = workflow.max_steps
        timeout_seconds = int(workflow.timeout_seconds or 600)
        auto_approve = bool(workflow.auto_approve)
        strict_approval = bool(workflow.strict_approval)

        if workflow.status == "paused":
            # 定时触发时调度器已经会写 workflow_paused；这里再兜一层，
            # 覆盖「排队期间工作流被暂停」以及手动触发竞态。
            run.skip_reason = "workflow_paused"
            await WorkflowRunRepository(session).finish_run(
                run, status="skipped", error_message="工作流已暂停，本次运行被跳过"
            )
            await session.commit()
            return "skipped"

        try:
            steps = validators.validate_definition(
                run.definition_snapshot or {}, max_steps=max_steps
            )
        except BadRequestException as exc:
            await WorkflowRunRepository(session).finish_run(
                run, status="failed", error_message=f"定义校验失败：{exc}"
            )
            await session.commit()
            return "failed"

        run_id = run.id
        run_as_type = run.run_as_type
        run_as_user_id = run.run_as_user_id
        run_as_end_user_id = run.run_as_end_user_id
        trigger_kind = run.trigger_kind

    # 会话内接管走最保守的审批口径：忽略工作流自己的 auto_approve/strict_approval。
    # 理由是这样一条 run 由终端用户的一条消息直接触发、每轮都跑，若沿用工作流上
    # 为「定时批量任务」配置的自动批准，终端用户就能借一次对话拿到本该人工确认的
    # 副作用。实测口径是「一律不自动批准」，再由 validators 保证分支内只出现
    # side_effect=none 的工具。
    if trigger_kind == "conversation":
        auto_approve = False
        strict_approval = False

    # 执行身份必须在执行前定下来：会话与工具审计都要求「恰有一个」身份。
    user_id: int | None = None
    end_user_id: int | None = None
    if run_as_type == "user":
        user_id = run_as_user_id
    elif run_as_type == "end_user":
        end_user_id = run_as_end_user_id
    else:
        await _finish(
            session_factory,
            workflow_run_id=run_id,
            status="failed",
            error_message=f"不支持的执行身份类型：{run_as_type}",
        )
        return "failed"

    if user_id is None and end_user_id is None:
        await _finish(
            session_factory,
            workflow_run_id=run_id,
            status="failed",
            error_message=(
                "工作流没有可用的执行身份：既没有后台用户（run_as_user_id），"
                "也没有终端用户（run_as_end_user_id）"
            ),
        )
        return "failed"

    # 每个分支在自己的 _execute_one_step 里建 policy（见 ExecutionTally 的说明），
    # 这里只持有跨分支汇总的计数器。
    tally = ExecutionTally()

    try:
        await asyncio.wait_for(
            execute_steps(
                session_factory,
                workflow_run_id=run_id,
                platform_id=platform_id,
                default_agent_id=default_agent_id,
                steps=steps,
                run_as_type=run_as_type,
                user_id=user_id,
                end_user_id=end_user_id,
                auto_approve=auto_approve,
                strict_approval=strict_approval,
                tally=tally,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        await fail_running_steps(
            session_factory, run_id, f"执行超时：超过 {timeout_seconds} 秒仍未完成"
        )
        await _finish(
            session_factory,
            workflow_run_id=run_id,
            status="failed",
            error_message=f"执行超时：超过 {timeout_seconds} 秒仍未完成",
            completed_steps=tally.completed_steps,
            auto_approved_count=tally.auto_approved_count,
        )
        return "failed"
    except (
        Exception
    ) as exc:  # noqa: BLE001 - 任何异常都必须落库为失败，否则永停 running
        message = f"执行失败：{type(exc).__name__}: {exc}"
        await fail_running_steps(session_factory, run_id, message)
        await _finish(
            session_factory,
            workflow_run_id=run_id,
            status="failed",
            error_message=message,
            completed_steps=tally.completed_steps,
            auto_approved_count=tally.auto_approved_count,
        )
        return "failed"

    await _finish(
        session_factory,
        workflow_run_id=run_id,
        status="completed",
        completed_steps=tally.completed_steps,
        auto_approved_count=tally.auto_approved_count,
    )
    return "completed"


def terminal_step_id(steps: list[dict[str, Any]]) -> str:
    """返回「终态步骤」的 step_id：没有任何步骤依赖它。

    汇合点就是终态步骤。若定义里有多个汇合点（各自独立的两条链），取定义里
    位次最大的那个——它是画布上最后画的一步，也是用户期望看到的那条线。
    """

    referenced: set[str] = set()
    for dependencies in validators.resolve_depends_on(steps):
        # 依赖可能带 ``@出口`` 后缀；比较「谁被依赖」时只认基础 step_id。
        referenced.update(validators.base_step_id(str(item)) for item in dependencies)
    sinks = [
        str(step["step_id"]) for step in steps if str(step["step_id"]) not in referenced
    ]
    if not sinks:
        # 全部步骤都被别人依赖，说明存在环——validate_definition 已经拦过，
        # 这里只做防御，避免调用方拿到一个空字符串。
        raise StepFailedError("工作流没有终态步骤：定义里所有步骤都依赖了别的步骤")
    return sinks[-1]


async def execute_orchestration_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_run_id: int,
    platform_id: int,
    default_agent_id: int,
    definition_snapshot: dict[str, Any],
    max_steps: int,
    run_as_type: str,
    user_id: int | None,
    end_user_id: int | None,
    timeout_seconds: int,
    turn_prefix: str,
) -> str:
    """执行一条「会话内接管」的编排运行，返回终态步骤的输出。

    与 ``run_workflow_run`` 的差别只有三点：

    1. run 记录由调用方（``workflows.orchestration``）建好，本函数不认领、不排队
       ——终端用户的那条消息正等着它的回话，塞进调度队列只会让回复延迟。
    2. 入口层步骤的提示词前面拼上本轮的用户消息与会话历史。
    3. 返回值是终态步骤的输出，调用方把它落成这一轮的 assistant 消息。

    审批口径固定为「一律不自动批准」：这条 run 由终端用户的输入直接触发，沿用
    工作流自身的 ``auto_approve`` 会让用户借一次对话绕开人工确认。
    """

    try:
        steps = validators.validate_definition(
            definition_snapshot or {}, max_steps=max_steps
        )
    except BadRequestException as exc:
        message = f"定义校验失败：{exc}"
        await _finish(
            session_factory,
            workflow_run_id=workflow_run_id,
            status="failed",
            error_message=message,
        )
        raise StepFailedError(message) from exc

    tally = ExecutionTally()
    try:
        outputs = await asyncio.wait_for(
            execute_steps(
                session_factory,
                workflow_run_id=workflow_run_id,
                platform_id=platform_id,
                default_agent_id=default_agent_id,
                steps=steps,
                run_as_type=run_as_type,
                user_id=user_id,
                end_user_id=end_user_id,
                auto_approve=False,
                strict_approval=False,
                tally=tally,
                turn_prefix=turn_prefix,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        message = f"执行超时：超过 {timeout_seconds} 秒仍未完成"
        await fail_running_steps(session_factory, workflow_run_id, message)
        await _finish(
            session_factory,
            workflow_run_id=workflow_run_id,
            status="failed",
            error_message=message,
            completed_steps=tally.completed_steps,
            auto_approved_count=tally.auto_approved_count,
        )
        raise StepFailedError(message) from exc
    except Exception as exc:  # noqa: BLE001 - 任何异常都要落库成失败
        message = f"执行失败：{type(exc).__name__}: {exc}"
        await fail_running_steps(session_factory, workflow_run_id, message)
        await _finish(
            session_factory,
            workflow_run_id=workflow_run_id,
            status="failed",
            error_message=message,
            completed_steps=tally.completed_steps,
            auto_approved_count=tally.auto_approved_count,
        )
        raise

    await _finish(
        session_factory,
        workflow_run_id=workflow_run_id,
        status="completed",
        completed_steps=tally.completed_steps,
        auto_approved_count=tally.auto_approved_count,
    )
    return outputs.get(terminal_step_id(steps), "")


async def execute_steps(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_run_id: int,
    platform_id: int,
    default_agent_id: int,
    steps: list[dict[str, Any]],
    run_as_type: str,
    user_id: int | None,
    end_user_id: int | None,
    auto_approve: bool,
    strict_approval: bool,
    tally: ExecutionTally,
    turn_prefix: str = "",
) -> dict[str, str]:
    """按拓扑分层执行全部步骤，把计数汇总进 ``tally``，返回各步的可见输出。

    层内并发、层间串行：同一层的步骤互不依赖，可以同时跑；下一层必须等本层
    全部产生终态记录。失败默认 fail-fast，但**先等已启动的同层分支收尾再抛**——
    直接取消会让已发生的工具副作用处于不确定状态，也会让步骤记录停在 running。

    执行的判据是**依赖边到达**（不是「依赖步骤成功」）：一条依赖边 ``a@handle``
    在上游 a 走到了 ``handle`` 出口时到达；一个步骤只要有**任意一条**依赖边到达
    就执行，全部依赖都没到达（上游被跳过、或走了别的分支）时它自己落
    ``status='skipped'`` 并沿下游继续传播。顶层步骤（无依赖）恒执行。这样条件
    分支不需要「汇聚步骤必须等齐所有分支」这种隐藏约定：写 ``depends_on`` 的
    人已经用出口把「等谁」说清楚了。

    ``turn_prefix`` 只加在**入口层**（第一层，即没有任何依赖的那一层）的 Agent
    步骤提示词前面，用于把「当前这轮用户消息 + 会话历史」喂给编排；后续层只拿
    自己的提示词与上游输出，这样并发分支之间不会因为共享整段对话而耦合。
    """

    layers = validators.execution_layers(steps)
    # seq 取定义里的位次而不是层内下标：它只用于稳定排序展示，
    # 并行之后「数组下标」已经不再等于执行顺序。
    seq_by_id = {str(step["step_id"]): index for index, step in enumerate(steps)}
    # 每个步骤声明的依赖条目原文（可能带 ``@出口``），用于判定「边是否到达」。
    dependency_map = {
        str(step["step_id"]): [str(entry) for entry in entries]
        for step, entries in zip(steps, validators.resolve_depends_on(steps))
    }
    outputs: dict[str, str] = {}
    # 已到达的出口：step_id → 它已经走到的出口集合。缺席或空集合都表示「还没到达」。
    arrived: dict[str, set[str]] = {}
    semaphore = asyncio.Semaphore(MAX_PARALLEL_STEPS)

    for layer_index, layer in enumerate(layers):
        runnable: list[dict[str, Any]] = []
        unreached: list[dict[str, Any]] = []
        for step in layer:
            entries = dependency_map.get(str(step["step_id"]), [])
            (runnable if _has_arrived(entries, arrived) else unreached).append(step)

        if unreached:
            # 被跳过的步骤也要留一条记录：否则「这一步去哪儿了」在运行记录里查不到，
            # 用户只会看到一条断掉的图。
            await _record_skipped_steps(
                session_factory,
                workflow_run_id=workflow_run_id,
                steps=unreached,
                seq_by_id=seq_by_id,
            )
            # 跳过的步骤按空输出参与后续渲染：没走的分支等于「没有产出」，这是
            # 正常结果而不是缺失。写入空串之后，下游的 {{step.output}} 与谓词取到
            # 的都是同一份语义（空串），不必在渲染层再判一次「是不是被跳过」。
            for step in unreached:
                outputs[str(step["step_id"])] = ""

        results = await asyncio.gather(
            *(
                _execute_one_step(
                    session_factory,
                    workflow_run_id=workflow_run_id,
                    platform_id=platform_id,
                    default_agent_id=default_agent_id,
                    step=step,
                    seq=seq_by_id[str(step["step_id"])],
                    # 传浅拷贝而不是同一个 dict：同层步骤之间的引用在保存期已被
                    # 拒绝（引用只能是祖先，祖先必在更早的层），这里把「只读」
                    # 从约定变成结构保证。
                    outputs=dict(outputs),
                    run_as_type=run_as_type,
                    user_id=user_id,
                    end_user_id=end_user_id,
                    auto_approve=auto_approve,
                    strict_approval=strict_approval,
                    semaphore=semaphore,
                    tally=tally,
                    turn_prefix=turn_prefix if layer_index == 0 else "",
                )
                for step in runnable
            ),
            # 不用默认的「一个失败就取消其余」：同层分支要么已经产生副作用，
            # 要么正在产生，收齐它们的终态再判定失败，运行记录才是可解释的。
            return_exceptions=True,
        )

        failure: BaseException | None = None
        for step, result in zip(runnable, results):
            if isinstance(result, BaseException):
                if failure is None:
                    failure = result
                continue
            step_id = str(step["step_id"])
            outputs[step_id] = result.visible
            arrived.setdefault(step_id, set()).add(result.handle)
            if result.completed:
                tally.completed_steps += 1
        if failure is not None:
            raise failure

    return outputs


def _has_arrived(entries: list[str], arrived: dict[str, set[str]]) -> bool:
    """「至少一条依赖边到达」才执行；没有任何依赖（顶层）恒执行。

    ``entries`` 是依赖条目原文。全部依赖都没到达时返回 ``False``——调用方据此
    把这一步记成 ``skipped``，而不是执行它或让整条 run 失败。
    """

    if not entries:
        return True
    for entry in entries:
        source, handle = validators.split_dependency(entry)
        if validators.normalize_handle(handle) in arrived.get(source, set()):
            return True
    return False


async def _record_skipped_steps(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_run_id: int,
    steps: list[dict[str, Any]],
    seq_by_id: dict[str, int],
) -> None:
    """给未到达的步骤各写一条 ``status='skipped'`` 记录（每步恰好一条）。

    ``uq_workflow_step_runs_run_step`` 约束「一条 run 内每个 step_id 只有一条
    记录」，因此这里必须在执行之前、且只写一次；跳过是正常结果而非错误，
    但记录里仍写明原因，否则前端只能显示一个没有解释的灰节点。
    """

    async with session_factory() as session:
        repository = WorkflowStepRunRepository(session)
        for step in steps:
            step_id = str(step["step_id"])
            step_run = await repository.create_step_run(
                run_id=workflow_run_id,
                step_id=step_id,
                seq=seq_by_id[step_id],
                node_type=str(step["kind"]),
                status="skipped",
            )
            await repository.finish_step_run(
                step_run, status="skipped", error_message=SKIPPED_MESSAGE
            )
        await session.commit()


async def _execute_one_step(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_run_id: int,
    platform_id: int,
    default_agent_id: int,
    step: dict[str, Any],
    seq: int,
    outputs: dict[str, str],
    run_as_type: str,
    user_id: int | None,
    end_user_id: int | None,
    auto_approve: bool,
    strict_approval: bool,
    semaphore: asyncio.Semaphore,
    tally: ExecutionTally,
    turn_prefix: str = "",
) -> _StepOutcome:
    """执行单个步骤：落 running 记录 → 重试 → 收尾落库 → 返回可见输出。

    并发闸在**整个步骤之外**（而不是每次尝试之外）：闸的目的是限制同时在跑的
    步骤数，重试属于同一步骤的延续，重新排队没有意义。
    """

    step_id = str(step["step_id"])
    kind = str(step["kind"])
    agent_id = int(step.get("agent_id") or default_agent_id)

    async with semaphore:
        async with session_factory() as session:
            step_run = await WorkflowStepRunRepository(session).create_step_run(
                run_id=workflow_run_id, step_id=step_id, seq=seq, node_type=kind
            )
            await session.commit()
            step_run_id = step_run.id

        logger.info(
            "Workflow step started run_id=%s step_id=%s seq=%s kind=%s",
            workflow_run_id,
            step_id,
            seq,
            kind,
        )

        if kind == "condition":
            # 条件步骤没有执行体：不建会话、不调模型、不调工具、无副作用，
            # 只按声明顺序求出第一个成立的分支名。命中结果同时作为可见输出与
            # 到达出口——前者让运行记录能解释「为什么走了这条线」，后者决定
            # 下游谁执行、谁跳过。
            branch = _match_branch(step, outputs)
            async with session_factory() as session:
                step_run = await session.get(WorkflowStepRun, step_run_id)
                if step_run is not None:
                    await WorkflowStepRunRepository(session).finish_step_run(
                        step_run,
                        status="succeeded",
                        model_visible_output=branch,
                        raw_output=branch,
                    )
                await session.commit()
            logger.info(
                "Workflow condition step finished run_id=%s step_id=%s branch=%s",
                workflow_run_id,
                step_id,
                branch,
            )
            return _StepOutcome(visible=branch, completed=True, handle=branch)

        # 步骤可声明 max_retries：失败后拿同一份输入重试，retry_count 记累计尝试次数。
        # 重试只覆盖「这一次执行抛错」，不改 on_error 策略——兜底值仍然要等全部
        # 尝试用尽之后才生效，否则重试就成了「一失败就吞掉」。
        attempts_total = max(1, int(step.get("max_retries") or 0) + 1)
        # 单步超时是 v1 之后补上的：run 级超时能兜住整条流程，但兜不住「某一步
        # 挂死、其余分支干等」；只在步骤显式声明时才加限制。
        step_timeout = step.get("timeout_seconds")
        # 分支内自己的 policy：共享一份实例会让「哪些批准属于哪一步」无从区分。
        policy = UnattendedPolicy(
            auto_approve=auto_approve, strict_approval=strict_approval
        )
        last_error: Exception | None = None
        raw = ""
        conversation_id: int | None = None
        loop_id: int | None = None
        succeeded = False
        attempt = 0

        try:
            for attempt in range(1, attempts_total + 1):
                try:
                    if kind == "agent":
                        prompt = _render_text(step.get("prompt") or "", outputs)
                        if turn_prefix:
                            prompt = f"{turn_prefix}\n\n【你的任务】\n{prompt}"
                        raw, conversation_id, loop_id = await _with_step_timeout(
                            _run_agent_step(
                                session_factory,
                                platform_id=platform_id,
                                agent_id=agent_id,
                                run_as_type=run_as_type,
                                user_id=user_id,
                                end_user_id=end_user_id,
                                prompt=prompt,
                                policy=policy,
                            ),
                            step_id=step_id,
                            timeout=step_timeout,
                        )
                    else:
                        arguments = _render_json(
                            step.get("tool_arguments") or {}, outputs
                        )
                        for name, selector in (
                            step.get("input_bindings") or {}
                        ).items():
                            arguments[name] = _resolve_selector(selector, outputs)
                        raw = await _with_step_timeout(
                            _run_tool_step(
                                session_factory,
                                platform_id=platform_id,
                                agent_id=agent_id,
                                tool_name=str(step.get("tool_name") or ""),
                                arguments=arguments,
                                user_id=user_id,
                                end_user_id=end_user_id,
                                policy=policy,
                            ),
                            step_id=step_id,
                            timeout=step_timeout,
                        )
                        conversation_id, loop_id = None, None
                except Exception as exc:  # noqa: BLE001 - 单步失败要按步骤策略处理
                    last_error = exc
                    logger.warning(
                        "Workflow step attempt failed run_id=%s step_id=%s "
                        "attempt=%s/%s error=%s: %s",
                        workflow_run_id,
                        step_id,
                        attempt,
                        attempts_total,
                        type(exc).__name__,
                        exc,
                    )
                    continue
                succeeded = True
                break
        finally:
            # 无论成功、失败还是被取消，本步用掉的自动批准数都要计入这条 run：
            # 批准发生过就是发生过，不能因为后续步骤失败而从记录里消失。
            # 这里的读改写之间没有 await，因此在 asyncio 单线程下本身是原子的；
            # 汇总进共享计数器而不是共享 policy，是为了让计数归属清晰。
            tally.auto_approved_count += policy.approved_count

        if succeeded:
            visible = validators.truncate_output(raw)
            async with session_factory() as session:
                step_run = await session.get(WorkflowStepRun, step_run_id)
                if step_run is not None:
                    await WorkflowStepRunRepository(session).finish_step_run(
                        step_run,
                        status="succeeded",
                        model_visible_output=visible,
                        raw_output=raw,
                        retry_count=attempt,
                        conversation_id=conversation_id,
                        agent_loop_run_id=loop_id,
                    )
                await session.commit()
            logger.info(
                "Workflow step finished run_id=%s step_id=%s chars=%s attempts=%s",
                workflow_run_id,
                step_id,
                len(raw),
                attempt,
            )
            return _StepOutcome(
                visible=visible, completed=True, handle=validators.DEFAULT_HANDLE
            )

        message = f"{type(last_error).__name__}: {last_error}"
        on_error = str(step.get("on_error") or "abort")
        fallback = str(step.get("default_output") or "")
        logger.warning(
            "Workflow step failed run_id=%s step_id=%s attempts=%s on_error=%s",
            workflow_run_id,
            step_id,
            attempts_total,
            on_error,
        )
        async with session_factory() as session:
            step_run = await session.get(WorkflowStepRun, step_run_id)
            if step_run is not None:
                await WorkflowStepRunRepository(session).finish_step_run(
                    step_run,
                    status="failed",
                    model_visible_output=(
                        fallback if on_error == "continue_with_default" else None
                    ),
                    raw_output=(
                        fallback if on_error == "continue_with_default" else None
                    ),
                    error_message=message,
                    on_error_applied=on_error == "continue_with_default",
                    retry_count=attempts_total,
                )
            await session.commit()

        if on_error == "continue_with_default":
            # 带兜底值继续：状态仍记为 failed，但 on_error_applied 为真，
            # 运行记录因此能如实指出「哪一步是带着兜底值过去的」。出口是成功出口：
            # 兜底值就是这一步交付给下游的东西。
            return _StepOutcome(
                visible=fallback, completed=True, handle=validators.DEFAULT_HANDLE
            )
        if on_error == "fail_branch":
            # 失败走隐式 ``failed`` 出口：这一步不再往上抛，整条 run 仍以
            # completed 收尾——补救由声明了 ``a@failed`` 的下游步骤负责，而只声明
            # ``a``（= @default）的下游会因为出口没到达而跳过。状态仍是 failed、
            # on_error_applied 仍是 False（失败没有被「处理掉」，只是换了条路走）。
            return _StepOutcome(
                visible="", completed=False, handle=validators.FAILED_HANDLE
            )
        raise StepFailedError(f"步骤 '{step_id}' 失败：{message}") from last_error


async def _with_step_timeout(awaitable: Any, *, step_id: str, timeout: Any) -> Any:
    """给单步套上可选超时；未声明 ``timeout_seconds`` 时不加限制。"""

    if not timeout:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=float(timeout))
    except asyncio.TimeoutError as exc:
        raise StepFailedError(
            f"步骤 '{step_id}' 执行超时：超过 {timeout} 秒仍未完成"
        ) from exc


async def _run_agent_step(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    platform_id: int,
    agent_id: int,
    run_as_type: str,
    user_id: int | None,
    end_user_id: int | None,
    prompt: str,
    policy: UnattendedPolicy,
) -> tuple[str, int | None, int | None]:
    """跑一轮 Agent，返回 (完整输出, 会话 ID, Agent 运行记录 ID)。

    显式传 ``allow_orchestration=False``：工作流的 Agent 步骤本身就是在「编排」，
    若这一步的 Agent 又绑定了工作流并被允许接管，就会无限递归。递归必须在这里
    断掉，而不是靠「用户别这么配」。
    """

    async with (
        session_factory() as session,
        session_factory() as tool_session,
    ):
        conversation, assistant, result = await execute_unattended_chat(
            session,
            platform_id=platform_id,
            agent_id=agent_id,
            run_as_type=run_as_type,
            user_id=user_id,
            end_user_id=end_user_id,
            message=prompt,
            model_id=None,
            confirmation_decider=build_confirmation_decider(policy),
            tool_session=tool_session,
            allow_orchestration=False,
        )
        await session.commit()
        # result.content 是这一轮模型的完整正文；assistant 记录只用于兜底，
        # 防止某些路径下 result.content 为空而输出缺失。
        raw = result.content or getattr(assistant, "content", "") or ""
        return raw, conversation.id, getattr(result, "loop_id", None)


async def _run_tool_step(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    platform_id: int,
    agent_id: int,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: int | None,
    end_user_id: int | None,
    policy: UnattendedPolicy,
) -> str:
    """直接调用一个已注册工具，返回其输出的文本形式。

    工具必须出现在该 Agent 的运行期工具清单里（内置 / MCP / 技能脚本 / 技能
    指令），因此这里复用与聊天完全相同的分派入口，工具支持范围不会漂移。
    """

    async with (
        session_factory() as session,
        session_factory() as tool_session,
    ):
        context = await load_runtime_context(
            AgentRepository(session),
            KnowledgeRepository(session),
            SkillRepository(session),
            McpRepository(session),
            BuiltinToolRepository(session),
            agent_id=agent_id,
            platform_id=platform_id,
        )
        tool = next(
            (
                candidate
                for candidate in build_runtime_tool_list(context)
                if getattr(candidate, "name", None) == tool_name
            ),
            None,
        )
        if tool is None:
            raise StepFailedError(
                f"工具 '{tool_name}' 不在 Agent {agent_id} 的可用工具里"
            )

        invoke = build_tool_invoker(
            platform_id=platform_id,
            agent_id=agent_id,
            builtin_repo=BuiltinToolRepository(tool_session),
            skill_repo=SkillRepository(tool_session),
            mcp_repo=McpRepository(tool_session),
            tool_session=tool_session,
            # 工具步骤没有会话：它不进模型上下文，因此没有可复用的会话 id。
            conversation_id_provider=lambda: None,
            user_id=user_id,
            platform_end_user_id=end_user_id,
            confirmation_decider=build_confirmation_decider(policy),
            # 工作流同样无人值守：用户记忆类工具在这里不接受写入。
            interactive=False,
        )
        outcome = await invoke(
            tool=tool,
            call={"id": f"workflow-step-{tool_name}", "args": arguments},
        )
        await session.commit()
        return _outcome_text(outcome, tool_name)


def _outcome_text(outcome: Any, tool_name: str) -> str:
    """把工具返回值转成文本；非完成状态一律当失败抛出。"""

    status = str(getattr(outcome, "status", "") or "")
    result = getattr(outcome, "result", None)
    error = getattr(outcome, "error", None)

    parts: list[str] = []
    if result is not None:
        parts.append(
            result
            if isinstance(result, str)
            else json.dumps(result, ensure_ascii=False, default=str)
        )
    if error:
        parts.append(
            error
            if isinstance(error, str)
            else json.dumps(error, ensure_ascii=False, default=str)
        )
    text = "\n".join(part for part in parts if part)

    if status and status != "completed":
        raise StepFailedError(f"工具 '{tool_name}' 返回 {status}：{text or '无输出'}")
    return text


def _render_text(template: str, outputs: dict[str, str]) -> str:
    """把提示词里的 ``{{step_id.output}}`` 替换成前序步骤的输出。"""

    def replace(match: Any) -> str:
        source_id = match.group(1)
        path = match.group(2)
        if path != OUTPUT_PATH:
            raise StepFailedError(
                f"不支持的输出路径 '{path}'：每一步只发布 '{OUTPUT_PATH}'"
            )
        if source_id not in outputs:
            raise StepFailedError(f"引用的步骤 '{source_id}' 尚无输出")
        return outputs[source_id]

    return validators.TEMPLATE_REFERENCE_PATTERN.sub(replace, template)


def _render_json(value: Any, outputs: dict[str, str]) -> Any:
    """递归渲染 JSON 结构里的字符串模板。"""

    if isinstance(value, str):
        return _render_text(value, outputs)
    if isinstance(value, dict):
        return {key: _render_json(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_json(item, outputs) for item in value]
    return value


def _resolve_selector(selector: Any, outputs: dict[str, str]) -> str:
    """解析一个 ``[step_id, path]`` 数组选择器。"""

    if not isinstance(selector, list) or len(selector) != 2:
        raise StepFailedError(f"非法输入绑定：{selector!r}")
    source_id, path = str(selector[0]), str(selector[1])
    if path != OUTPUT_PATH:
        raise StepFailedError(
            f"不支持的输出路径 '{path}'：每一步只发布 '{OUTPUT_PATH}'"
        )
    if source_id not in outputs:
        raise StepFailedError(f"引用的步骤 '{source_id}' 尚无输出")
    return outputs[source_id]


def evaluate_predicate(predicate: dict[str, Any], outputs: dict[str, str]) -> bool:
    """对一份已通过保存期校验的结构化谓词求值（纯数据，无副作用）。

    形状合法性由 ``validators`` 在保存期判定，这里只负责求值；遇到白名单外的
    算子仍然抛错（定义可能来自数据库里的历史快照，不能假设它一定干净）。

    左操作数指向的上游若没有输出（该步被跳过、或走的是 ``failed`` 出口），按
    **空字符串**参与比较。跳过是条件分支的正常结果，把它变成运行失败会让
    「另一条分支」这种最常见的用法直接不可用。
    """

    op = str(predicate.get("op") or "")
    if op in validators.PREDICATE_LOGICAL_OPS:
        values = [
            evaluate_predicate(child, outputs)
            for child in (predicate.get("children") or [])
        ]
        if op == "all":
            return all(values)
        if op == "any":
            return any(values)
        # not：保存期保证恰好一个子节点，因此等价于「子节点为假」。
        return not any(values)
    if op not in validators.PREDICATE_OPS:
        raise StepFailedError(f"未知的条件谓词算子：{op}")

    value = _predicate_operand(predicate.get("left"), outputs)
    right = predicate.get("right")
    if op == "equals":
        return value == str(right)
    if op == "contains":
        return str(right) in value
    if op == "not_empty":
        return bool(value.strip())
    # matches：正则在保存期已预编译过，这里只做匹配。
    return re.search(str(right), value) is not None


def _predicate_operand(left: Any, outputs: dict[str, str]) -> str:
    """解析谓词左操作数（``{{step_id.output}}``）并取出上游输出。

    取不到输出时返回空字符串而不是抛错：上游被跳过属于正常执行路径（详见
    ``evaluate_predicate``）。只有「写法本身不合法」才是错误。
    """

    match = validators.TEMPLATE_REFERENCE_PATTERN.fullmatch(str(left or "").strip())
    if match is None:
        raise StepFailedError(
            "条件谓词的左操作数必须是 '{{step_id.output}}' 形式，收到：" + repr(left)
        )
    source_id, path = match.groups()
    if path != OUTPUT_PATH:
        raise StepFailedError(
            f"不支持的输出路径 '{path}'：每一步只发布 '{OUTPUT_PATH}'"
        )
    return outputs.get(source_id, "")


def _match_branch(step: dict[str, Any], outputs: dict[str, str]) -> str:
    """按声明顺序返回第一个成立的分支名。

    无条件兜底分支必然命中（保存期要求它存在且排在最后），因此走到函数末尾的
    ``raise`` 只会在定义被写坏时触发——那时把它当运行失败比静默取第一个分支好，
    否则用户会拿到一个「看起来跑通了、其实判错了」的结果。
    """

    for branch in step.get("branches") or []:
        when = branch.get("when")
        if when is None or evaluate_predicate(when, outputs):
            return str(branch.get("name"))
    raise StepFailedError(
        f"条件步骤 '{step.get('step_id')}' 没有任何分支命中：定义缺少无条件兜底分支"
    )


async def fail_running_steps(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_run_id: int,
    message: str,
) -> int:
    """把一次运行里仍是 running 的步骤标记为失败。"""

    async with session_factory() as session:
        failed = await WorkflowStepRunRepository(session).fail_running_steps(
            workflow_run_id, error_message=message
        )
        await session.commit()
        return failed


async def _finish(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_run_id: int,
    status: str,
    error_message: str | None = None,
    completed_steps: int | None = None,
    auto_approved_count: int | None = None,
) -> None:
    """在独立 Session 里给运行记录收尾。"""

    async with session_factory() as session:
        run = await session.get(WorkflowRun, workflow_run_id)
        if run is None:
            return
        await WorkflowRunRepository(session).finish_run(
            run,
            status=status,
            error_message=error_message,
            completed_steps=completed_steps,
            auto_approved_count=auto_approved_count,
        )
        await session.commit()


__all__ = [
    "StepFailedError",
    "execute_orchestration_run",
    "run_workflow_run",
    "terminal_step_id",
]
