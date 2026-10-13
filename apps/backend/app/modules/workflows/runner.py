"""工作流执行引擎：按顺序把一次工作流运行跑完。

与 ``app/modules/tasks/runner.py`` 是同一族代码，差别只在「一轮」变成了
「一串步骤」：

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

失败策略做在步骤属性上而不是流程级，是调研 Dify / n8n / GitHub Actions 后的
共同结论：只有步骤级才能表达「这一步失败可以兜底，那一步失败必须停」。
"""

from __future__ import annotations

import asyncio
import json
import logging
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


class StepFailedError(Exception):
    """单步执行失败；消息会原样进入步骤运行记录，供排障。"""


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

    policy = UnattendedPolicy(
        auto_approve=auto_approve,
        strict_approval=strict_approval,
    )

    try:
        completed_steps = await asyncio.wait_for(
            _execute_steps(
                session_factory,
                workflow_run_id=run_id,
                platform_id=platform_id,
                default_agent_id=default_agent_id,
                steps=steps,
                run_as_type=run_as_type,
                user_id=user_id,
                end_user_id=end_user_id,
                policy=policy,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        await _fail_running_steps(
            session_factory, run_id, f"执行超时：超过 {timeout_seconds} 秒仍未完成"
        )
        await _finish(
            session_factory,
            workflow_run_id=run_id,
            status="failed",
            error_message=f"执行超时：超过 {timeout_seconds} 秒仍未完成",
            completed_steps=0,
            auto_approved_count=policy.approved_count,
        )
        return "failed"
    except Exception as exc:  # noqa: BLE001 - 任何异常都必须落库为失败，否则永停 running
        message = f"执行失败：{type(exc).__name__}: {exc}"
        await _fail_running_steps(session_factory, run_id, message)
        await _finish(
            session_factory,
            workflow_run_id=run_id,
            status="failed",
            error_message=message,
            completed_steps=0,
            auto_approved_count=policy.approved_count,
        )
        return "failed"

    await _finish(
        session_factory,
        workflow_run_id=run_id,
        status="completed",
        completed_steps=completed_steps,
        auto_approved_count=policy.approved_count,
    )
    return "completed"


async def _execute_steps(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_run_id: int,
    platform_id: int,
    default_agent_id: int,
    steps: list[dict[str, Any]],
    run_as_type: str,
    user_id: int | None,
    end_user_id: int | None,
    policy: UnattendedPolicy,
) -> int:
    """按顺序执行全部步骤，返回成功完成（含用兜底值继续）的步骤数。"""

    outputs: dict[str, str] = {}
    completed = 0

    for seq, step in enumerate(steps):
        step_id = str(step["step_id"])
        kind = str(step["kind"])
        agent_id = int(step.get("agent_id") or default_agent_id)

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

        # 步骤可声明 max_retries：失败后拿同一份输入重试，retry_count 记累计尝试次数。
        # 重试只覆盖「这一次执行抛错」，不改 on_error 策略——兜底值仍然要等全部
        # 尝试用尽之后才生效，否则重试就成了「一失败就吞掉」。
        attempts_total = max(1, int(step.get("max_retries") or 0) + 1)
        last_error: Exception | None = None
        raw = ""
        conversation_id: int | None = None
        loop_id: int | None = None
        succeeded = False

        for attempt in range(1, attempts_total + 1):
            try:
                if kind == "agent":
                    prompt = _render_text(step.get("prompt") or "", outputs)
                    raw, conversation_id, loop_id = await _run_agent_step(
                        session_factory,
                        platform_id=platform_id,
                        agent_id=agent_id,
                        run_as_type=run_as_type,
                        user_id=user_id,
                        end_user_id=end_user_id,
                        prompt=prompt,
                        policy=policy,
                    )
                else:
                    arguments = _render_json(step.get("tool_arguments") or {}, outputs)
                    for name, selector in (step.get("input_bindings") or {}).items():
                        arguments[name] = _resolve_selector(selector, outputs)
                    raw = await _run_tool_step(
                        session_factory,
                        platform_id=platform_id,
                        agent_id=agent_id,
                        tool_name=str(step.get("tool_name") or ""),
                        arguments=arguments,
                        user_id=user_id,
                        end_user_id=end_user_id,
                        policy=policy,
                    )
                    conversation_id, loop_id = None, None
            except Exception as exc:  # noqa: BLE001 - 单步失败要按步骤策略处理
                last_error = exc
                logger.warning(
                    "Workflow step attempt failed run_id=%s step_id=%s attempt=%s/%s error=%s: %s",
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

        if succeeded:
            visible = validators.truncate_output(raw)
            outputs[step_id] = visible
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
            completed += 1
            logger.info(
                "Workflow step finished run_id=%s step_id=%s chars=%s attempts=%s",
                workflow_run_id,
                step_id,
                len(raw),
                attempt,
            )
            continue

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
                    model_visible_output=fallback if on_error == "continue_with_default" else None,
                    raw_output=fallback if on_error == "continue_with_default" else None,
                    error_message=message,
                    on_error_applied=on_error == "continue_with_default",
                    retry_count=attempts_total,
                )
            await session.commit()

        if on_error == "continue_with_default":
            # 带兜底值继续：状态仍记为 failed，但 on_error_applied 为真，
            # 运行记录因此能如实指出「哪一步是带着兜底值过去的」。
            outputs[step_id] = fallback
            completed += 1
            continue
        raise StepFailedError(f"步骤 '{step_id}' 失败：{message}") from last_error

    return completed


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
    """跑一轮 Agent，返回 (完整输出, 会话 ID, Agent 运行记录 ID)。"""

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
        raise StepFailedError(
            f"工具 '{tool_name}' 返回 {status}：{text or '无输出'}"
        )
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


async def _fail_running_steps(
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


__all__ = ["StepFailedError", "run_workflow_run"]
