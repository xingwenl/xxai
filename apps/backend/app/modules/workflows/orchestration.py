"""会话内编排接管：把 Agent 的一轮消息交给一条工作流完成。

用户的决策是「Agent 绑定编排，每轮消息都跑一次：跑并行分支 + 汇聚，汇聚步骤
的输出就是这一轮的回复」。这个模块只负责把「一轮会话消息」翻译成「一条
``trigger_kind="conversation"`` 的工作流运行」，执行本身全部交给
``workflows.runner``——编排引擎只有一份，调度口径才不会漂移。

三条刻意的边界：

1. **本模块不 import ``conversation``**。接管发生在会话链路内部，若反过来由
   编排模块去调会话服务，两边就会形成环；执行步骤所需的一切都由调用方以参数
   传入（身份、平台、前缀文本）。
2. **不做逐 token 流式**。汇聚步骤要等全部分支产生终态才能开始，输出只可能在
   末尾成形。对外仍然产出同一套 ``AgentEvent``：一条 ``message_delta``（整段
   内容）+ 一条 ``completed``，下游的 ``stream_runtime_as_conversation``、SSE
   序列化与 assistant 落库因此完全不用改。
3. **入口层才带上下文**。会话历史与本轮消息渲染成 ``turn_prefix``，只拼在
   入口层（第一层）Agent 步骤的提示词前面；分支 Agent 各自只拿自己那一步的
   提示词与上游输出，不会因为共享整段对话而互相耦合。

递归由调用侧的 ``allow_orchestration=False`` 断开：工作流里的 Agent 步骤本身
就在编排，若那一步的 Agent 又绑定工作流并被允许接管，就会无限套娃。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.agent_runtime.contracts import AgentEvent, AgentEventType
from app.modules.workflows import validators
from app.modules.workflows.models import Workflow
from app.modules.workflows.repositories import WorkflowRunRepository
from app.modules.workflows.runner import StepFailedError, execute_orchestration_run

logger = logging.getLogger(__name__)


def orchestration_workflow_id(context: Any) -> int | None:
    """取出该 Agent 绑定的编排工作流 ID；未绑定时返回 ``None``。

    这是「接管与否」的唯一判定入口：绑定字段放在 Agent 而不是 Workflow 上，
    因为 ``Workflow.agent_id`` 是「工作流用哪个 Agent 当默认执行者」的反向
    外键，语义不能复用；而仓库里并不存在「已发布工作流」这种状态。
    """

    agent = getattr(context, "agent", None)
    if agent is None:
        return None
    workflow_id = getattr(agent, "orchestration_workflow_id", None)
    return int(workflow_id) if workflow_id else None


def build_turn_prefix(history: list[Any] | None, message: str) -> str:
    """把会话历史与本轮用户消息渲染成入口步骤的提示词前缀。

    用户选择「每轮都带上会话历史」，因此这里把历史拍平成纯文本；只保留
    用户/助手消息，工具消息属于上一步的执行细节，放进提示词只会挤占预算。
    """

    lines = _history_lines(history)
    return "\n".join(
        [
            "【最近的会话历史】",
            "\n".join(lines) if lines else "（没有更早的历史）",
            "",
            "【本轮用户消息】",
            message,
        ]
    )


def _history_lines(history: list[Any] | None) -> list[str]:
    """把异构的历史条目（ORM 对象 / langchain 消息 / dict）统一成文本行。"""

    lines: list[str] = []
    for item in history or []:
        role, content = _role_and_content(item)
        if role not in ("user", "assistant") or not content:
            continue
        lines.append(f"【{'用户' if role == 'user' else '助手'}】{content}")
    return lines


def _role_and_content(item: Any) -> tuple[str | None, str | None]:
    """容忍三种历史形状：ORM 会话消息、langchain 消息对象、普通 dict。"""

    role = getattr(item, "role", None)
    content = getattr(item, "content", None)
    if role is None:
        # langchain 消息只有类名可辨；这里刻意不 import langchain，
        # 免得把编排模块绑到一个具体模型 SDK 上。
        class_name = type(item).__name__
        role = {
            "HumanMessage": "user",
            "AIMessage": "assistant",
            "ToolMessage": "tool",
            "SystemMessage": "system",
        }.get(class_name)
    if isinstance(item, dict):
        role = item.get("role") or role
        content = item.get("content") or content
    if not isinstance(content, str):
        # 多模态消息的 content 可能是分片列表，取其中的文本片段。
        content = _flatten_text(content)
    return role, content


def _flatten_text(value: Any) -> str | None:
    """从多模态 content 分片里抽出纯文本。"""

    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    pieces: list[str] = []
    for part in value:
        if isinstance(part, str):
            pieces.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str):
            pieces.append(part["text"])
    joined = "\n".join(piece for piece in pieces if piece)
    return joined or None


async def run_orchestration_turn(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    platform_id: int,
    agent_id: int,
    workflow_id: int,
    run_as_type: str,
    user_id: int | None,
    end_user_id: int | None,
    turn_prefix: str,
) -> tuple[str, int]:
    """建一条会话触发的运行并执行，返回 ``(终态输出, 运行记录 ID)``。

    运行记录先写后执行：终端用户在这条消息上等的就是这次编排，先落一条
    ``running`` 才有「现在卡在哪一步」可看。``trigger_kind="conversation"``
    同时决定了它不参与「同一工作流只能有一条 running」的部分唯一索引——
    那条约束只保护无人值守触发，否则两个用户同时说话就会互相把对方改写成
    skipped。
    """

    async with session_factory() as session:
        workflow = await session.get(Workflow, workflow_id)
        if workflow is None or workflow.platform_id != platform_id:
            raise StepFailedError(f"编排工作流 {workflow_id} 不存在或不属于当前平台")
        if workflow.status != "active":
            raise StepFailedError(f"编排工作流 '{workflow.name}' 已暂停，无法接管会话")
        definition_snapshot = dict(workflow.definition or {})
        steps = validators.steps_from_definition(definition_snapshot)
        run = await WorkflowRunRepository(session).create_run(
            workflow_id=workflow.id,
            status="running",
            trigger_kind="conversation",
            definition_version_id=workflow.version,
            definition_snapshot=definition_snapshot,
            total_steps=len(steps),
            run_as_type=run_as_type,
            run_as_user_id=user_id,
            run_as_end_user_id=end_user_id,
            # 会话触发不走调度器，因此直接标记已开始，看门狗不会把它当成
            # 「排队太久还没被认领」的任务。
            started_at=datetime.now(UTC),
        )
        await session.commit()
        workflow_run_id = run.id
        max_steps = workflow.max_steps
        timeout_seconds = workflow.timeout_seconds
        default_agent_id = workflow.agent_id

    logger.info(
        "Conversation orchestration started workflow_id=%s workflow_run_id=%s agent_id=%s",
        workflow_id,
        workflow_run_id,
        agent_id,
    )
    content = await execute_orchestration_run(
        session_factory,
        workflow_run_id=workflow_run_id,
        platform_id=platform_id,
        default_agent_id=default_agent_id,
        definition_snapshot=definition_snapshot,
        max_steps=max_steps,
        run_as_type=run_as_type,
        user_id=user_id,
        end_user_id=end_user_id,
        timeout_seconds=timeout_seconds,
        turn_prefix=turn_prefix,
    )
    return content, workflow_run_id


async def stream_orchestration_turn(
    session_factory: async_sessionmaker[AsyncSession],
    **kwargs: Any,
) -> AsyncIterator[AgentEvent]:
    """把一次编排转成与模型流式同形的 ``AgentEvent`` 序列。

    失败不抛给上层：SSE 入口把「异常」当成连接错误，而这里的失败是一条正常的
    运行结果。转成 ``error`` 事件后，既有的消费分支会把 loop 与生成步骤一起
    置为 failed，公开响应格式与单 Agent 链路完全一致。
    """

    try:
        content, workflow_run_id = await run_orchestration_turn(
            session_factory, **kwargs
        )
    except Exception as error:  # noqa: BLE001 - 失败必须转成 error 事件而非抛出
        logger.warning("Conversation orchestration failed: %s", error)
        yield AgentEvent(
            type=AgentEventType.ERROR,
            payload={
                "code": "orchestration_failed",
                "message": str(error).strip() or type(error).__name__,
                "retryable": False,
            },
        )
        return

    yield AgentEvent(
        type=AgentEventType.MESSAGE_DELTA,
        payload={"content": content, "workflow_run_id": workflow_run_id},
    )
    yield AgentEvent(
        type=AgentEventType.COMPLETED,
        payload={"content": content, "workflow_run_id": workflow_run_id},
    )


__all__ = [
    "build_turn_prefix",
    "orchestration_workflow_id",
    "run_orchestration_turn",
    "stream_orchestration_turn",
]
