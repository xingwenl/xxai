"""运行时工具分派：把「模型要调用的工具」落到具体执行器上。

抽出来的原因：这段分派原本只写在 conversation 的 REST 聊天接口里，
任务功能需要在**无人值守**场景下复用同一份分派逻辑。复制一份的话，
两边的工具支持范围迟早漂移（例如新增一类工具只改了其中一处）。

本模块只负责「认领工具并调用」，不关心调用者是谁；无人值守下的
审批策略由调用方通过 ``confirmation_decider`` 注入。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.agent_runtime.contracts import ToolCall
from app.modules.asset.repositories import AssetRepository
from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.mcp.runtime import RepositoryMcpExecutor
from app.modules.mcp.services import invoke_tool, resolve_tool_confirmation
from app.modules.skill.services import load_bound_skill_instruction
from app.modules.skill_runner.client import SkillRunnerClient
from app.modules.skill_runner.services import execute_skill_script
from app.modules.tool_approval.contracts import (
    ConfirmationDecision,
    ConfirmationDecider,
)

__all__ = [
    "ConfirmationDecision",
    "ConfirmationDecider",
    "ToolDispatchError",
    "build_tool_invoker",
]


class ToolDispatchError(Exception):
    """无人值守下无法执行的工具类型，带稳定错误码便于留痕与排障。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.message = message


def build_tool_invoker(
    *,
    platform_id: int,
    agent_id: int,
    builtin_repo: Any,
    skill_repo: Any,
    mcp_repo: Any,
    tool_session: Any,
    conversation_id_provider: Callable[[], int | None],
    user_id: int | None = None,
    platform_end_user_id: int | None = None,
    confirmation_decider: ConfirmationDecider | None = None,
    loop_run_id_provider: Callable[[], int | None] | None = None,
) -> Callable[..., Awaitable[Any]]:
    """构造工具调用函数，供 REST 聊天与无人值守任务共用。

    ``conversation_id_provider`` 用回调而不是直接传值：会话 id 要等
    ``execute_chat`` 内部解析会话后才存在，而分派函数必须先构造出来。
    ``loop_run_id_provider`` 同理——运行记录在 ``build_loop_with_steps``
    里才创建，委派类工具要用它把子运行挂到父运行下；未传时恒为 None，
    非委派场景行为不变。
    """

    loaded_skill_cache: dict[str, Any] = {}

    async def invoke(**kwargs) -> Any:
        typed_call = kwargs.get("call")
        if isinstance(typed_call, ToolCall):
            kwargs["call"] = {
                "id": typed_call.id,
                "args": typed_call.arguments,
            }
            if kwargs.get("tool") is None and typed_call.name:
                kwargs["tool_name"] = typed_call.name
        tool = kwargs.get("tool")
        kind = getattr(tool, "kind", None)

        if kind == "builtin":
            return await invoke_builtin_tool(
                builtin_repo,
                AssetRepository(tool_session),
                tool=tool,
                call=kwargs["call"],
                platform_id=platform_id,
                agent_id=agent_id,
                conversation_id=conversation_id_provider(),
                user_id=user_id,
                platform_end_user_id=platform_end_user_id,
                session=tool_session,
                loop_run_id=(
                    loop_run_id_provider() if loop_run_id_provider is not None else None
                ),
                confirmation_decider=confirmation_decider,
            )

        if kind == "skill_script":
            return await execute_skill_script(
                skill_repo,
                SkillRunnerClient(),
                tool=tool,
                call=kwargs["call"],
                platform_id=platform_id,
                agent_id=agent_id,
                user_id=user_id,
            )

        if kind == "skill_instruction":
            slug = kwargs.get("call", {}).get("args", {}).get("slug")
            if isinstance(slug, str) and slug in loaded_skill_cache:
                return loaded_skill_cache[slug]
            outcome = await load_bound_skill_instruction(
                skill_repo,
                platform_id,
                agent_id,
                slug,
            )
            if isinstance(slug, str) and outcome.status == "completed":
                loaded_skill_cache[slug] = outcome
            return outcome

        if hasattr(tool, "server_id"):
            return await _invoke_mcp_tool(
                tool=tool,
                call=kwargs["call"],
                mcp_repo=mcp_repo,
                platform_id=platform_id,
                agent_id=agent_id,
                user_id=user_id,
                platform_end_user_id=platform_end_user_id,
                confirmation_decider=confirmation_decider,
            )

        # 剩下的都是页面宿主工具：它依赖浏览器连接回传结果。无人值守运行
        # 没有承载方，必须立刻给出明确失败，而不是等一个不会到来的回传。
        raise ToolDispatchError(
            "host_tool_unavailable_in_unattended_run",
            "宿主工具需要页面连接回传结果，无人值守任务不可用",
        )

    return invoke


async def _invoke_mcp_tool(
    *,
    tool,
    call: dict,
    mcp_repo,
    platform_id: int,
    agent_id: int,
    user_id: int | None,
    platform_end_user_id: int | None,
    confirmation_decider: ConfirmationDecider | None,
) -> Any:
    """调用 MCP 工具；需要确认时按注入的策略决定批准或拒绝。"""

    executor = RepositoryMcpExecutor(mcp_repo)
    outcome = await invoke_tool(
        mcp_repo,
        executor,
        platform_id=platform_id,
        agent_id=agent_id,
        server_id=tool.server_id,
        tool_name=tool.name,
        arguments=call.get("args", {}),
        user_id=user_id,
        platform_end_user_id=platform_end_user_id,
    )
    if getattr(outcome, "status", None) != "confirmation_required":
        return outcome
    if confirmation_decider is None:
        # 未注入策略时保持既有行为：确认请求作为结果交回调用方。
        return outcome

    decision = await confirmation_decider(tool, outcome)
    if decision is None:
        return outcome

    resolved = await resolve_tool_confirmation(
        mcp_repo,
        executor,
        confirmation_id=outcome.confirmation_id,
        platform_id=platform_id,
        approved=decision.approved,
        user_id=user_id,
        platform_end_user_id=platform_end_user_id,
    )
    if decision.approved or not decision.message:
        return resolved
    # 拒绝时把「为什么没执行」一并带给模型，避免它无从调整。
    return resolved.model_copy(
        update={
            "result": {
                "status": "rejected",
                "auto_approved": False,
                "message": decision.message,
            }
        }
    )
