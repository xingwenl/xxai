"""内置业务工具：让 Agent 在会话中为自己创建定时任务。

边界（与 spec 一致）：
- Agent 只能创建**自己**的任务：``created_by_type=agent``、
  ``created_by_agent_id=当前 Agent``、归属为当前会话用户；
- 执行身份为当前会话用户，这样任务跑起来时看到的数据与工具权限
  与用户本人发起时一致；
- 创建即启用；同样受「最小间隔 1 分钟」与单平台任务数上限约束；
- 本工具不改也不删任何任务，只负责创建。
"""

from __future__ import annotations

from app.modules.tasks import services as task_services
from app.modules.tasks.schemas import TaskCreate
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)
from app.shared.exceptions import AppException


@business_tool(
    name="create_task",
    description=(
        "为用户创建一个定时任务：到点后系统会自动运行一轮对话并执行你写下的指令。"
        "适用场景：用户要求「每天/每周/每隔一段时间提醒或检查某事」「到某个时间点做一件事」。"
        "注意：任务会无人值守地自动运行，执行期间没有人可以确认操作，"
        "因此涉及支付等不可逆操作的任务不要创建。"
        "用法：name 是任务名称，prompt 是到点后发给自己的完整指令"
        "（要写成独立可执行的句子，因为运行时看不到当前对话上下文）；"
        "trigger_type=cron 时填五段式 cron（分 时 日 月 周），"
        "trigger_type=once 时填 run_at（ISO 8601 时间）；timezone 用 IANA 时区名，默认 Asia/Shanghai。"
        "最小触发间隔为 1 分钟，更频繁的表达式会被拒绝。"
        "结果使用：返回任务的 id、名称与下次运行时间；"
        "任务会绑定当前会话的执行身份（后台会话绑定该登录用户，"
        "Embed 会话绑定该终端用户），后台用户创建的任务可在「任务」页面查看、暂停或删除。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
                "description": "任务名称，用于列表展示",
            },
            "prompt": {
                "type": "string",
                "minLength": 1,
                "description": "到点后发给自己的指令，必须是独立可执行的完整句子",
            },
            "trigger_type": {
                "type": "string",
                "enum": ["cron", "once"],
                "description": "触发类型：cron 周期触发 / once 一次性触发",
            },
            "cron_expression": {
                "type": "string",
                "description": "五段式 cron（分 时 日 月 周），trigger_type=cron 时必填，最小间隔 1 分钟",
            },
            "run_at": {
                "type": "string",
                "description": "一次性执行时刻，ISO 8601 格式（如 2026-09-20T09:00:00+08:00），trigger_type=once 时必填",
            },
            "timezone": {
                "type": "string",
                "description": "IANA 时区名，用于解释 cron 与 run_at，默认 Asia/Shanghai",
            },
        },
        "required": ["name", "prompt", "trigger_type"],
        "additionalProperties": False,
    },
)
async def create_task_business(args: dict, ctx: BusinessToolContext) -> dict:
    """创建一条由当前 Agent 发起、绑定当前会话执行身份的任务。"""

    if ctx.session is None:
        raise BusinessToolError(
            "task_create_failed",
            "无法创建定时任务：当前工具上下文没有可用的数据库会话。",
        )

    from datetime import datetime

    trigger_type = str(args.get("trigger_type") or "cron").strip()
    run_at_raw = args.get("run_at")
    run_at: datetime | None = None
    if isinstance(run_at_raw, str) and run_at_raw.strip():
        try:
            run_at = datetime.fromisoformat(run_at_raw.strip())
        except ValueError as exc:
            raise BusinessToolError("invalid_run_at") from exc

    payload = TaskCreate(
        name=str(args.get("name") or "").strip(),
        prompt=str(args.get("prompt") or "").strip(),
        agent_id=ctx.agent_id,
        trigger_type=trigger_type,  # type: ignore[arg-type]
        cron_expression=(args.get("cron_expression") or None),
        run_at=run_at,
        timezone=str(args.get("timezone") or "Asia/Shanghai"),
    )
    if not payload.name or not payload.prompt:
        raise BusinessToolError("invalid_arguments")

    # 身份解析：会话的 principal 恰有一个，工具必须按实际存在的那个来建任务。
    # 后台会话有 user_id；Embed 会话只有 platform_end_user_id（终端用户）。
    # 两者都没有时说明调用方没有传身份，此时给出可操作的中文说明，
    # 而不是抛一个模型看不懂的裸错误码。
    if ctx.user_id is not None:
        owner_user_id = ctx.user_id
        run_as_type = "user"
        run_as_user_id = ctx.user_id
        run_as_end_user_id = None
    elif ctx.platform_end_user_id is not None:
        # 终端用户任务：没有后台归属，靠 run_as_end_user_id 标识执行身份。
        owner_user_id = None
        run_as_type = "end_user"
        run_as_user_id = None
        run_as_end_user_id = ctx.platform_end_user_id
    else:
        raise BusinessToolError(
            "task_requires_user_identity",
            "无法创建定时任务：当前会话没有可用的用户身份，任务必须绑定一个"
            "执行身份（后台用户或终端用户），运行时会以该身份执行。"
            "请确认调用方已传入 user_id 或 platform_end_user_id。",
        )

    try:
        task = await task_services.create_task(
            ctx.session,
            platform_id=ctx.platform_id,
            payload=payload,
            owner_user_id=owner_user_id,
            created_by_type="agent",
            created_by_agent_id=ctx.agent_id,
            run_as_type=run_as_type,
            run_as_user_id=run_as_user_id,
            run_as_end_user_id=run_as_end_user_id,
        )
    except AppException as exc:
        # 业务规则拒绝（间隔过短、超上限、Agent 不可用等）：
        # 转成稳定错误码，让模型据此向用户解释，而不是抛栈。
        raise BusinessToolError(_error_code(exc), exc.message) from exc

    return {
        "kind": "create_task",
        "task": {
            "id": task.id,
            "name": task.name,
            "trigger_type": task.trigger_type,
            "cron_expression": task.cron_expression,
            "run_at": task.run_at.isoformat() if task.run_at else None,
            "timezone": task.timezone,
            "status": task.status,
            "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        },
        "message": (
            f"任务「{task.name}」已创建并启用，可在任务页面查看、暂停或删除。"
        ),
    }


def _error_code(exc: AppException) -> str:
    """把服务层异常映射为 LLM 可见的稳定错误码。"""

    message = (exc.message or "").lower()
    if "interval" in message:
        return "task_interval_too_short"
    if "limit" in message:
        return "task_limit_reached"
    if "cron" in message:
        return "invalid_cron_expression"
    if "agent" in message:
        return "agent_not_available"
    if "timezone" in message:
        return "invalid_timezone"
    return "task_create_failed"
