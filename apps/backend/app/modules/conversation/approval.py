"""REST / SSE 对话通路的交互式工具确认裁决器。

为什么要单独一层：``conversation`` 模块的流式对话没有「等待用户回话」的连接级通道
（WS 网关有 ``asyncio.Future`` 等待通道），因此这里的裁决器不能像网关那样当场等
结果，而是采取「落库 + 挂起」：把确认记录写进 ``tool_confirmations``，返回
``defer=True`` 让运行停在 ``confirmation_required``，再由
``POST /agents/{agent_id}/runs/{loop_run_id}/resolve`` 续跑。

副作用真值一律取注册表定义（``invoke_builtin_tool`` 传入的 ``definition`` 就是注册表
里的那一个），而不是调用方自称的副作用，避免旁路。
"""

from __future__ import annotations

from typing import Any

from app.modules.tool_approval.contracts import (
    DEFERRED_FOR_CONFIRMATION,
    NAVIGATION_SIDE_EFFECT,
    REMEMBERED_APPROVAL,
    ConfirmationDecision,
)
from app.modules.tool_approval.services import ToolApprovalService
from app.modules.tools.side_effects import coerce_side_effect

# 确认来源：续跑时要按来源选择「执行器」（内置工具走 handler、MCP 走 resolve+执行）。
SOURCE_BUILTIN = "builtin"
SOURCE_MCP = "mcp"


class InteractiveConfirmationDecider:
    """把「需要确认」的工具调用挂起成一条持久化确认记录。

    与网关裁决器的区别：网关在连接内 ``await`` 用户决定并当场返回批准/拒绝；
    这里只负责「问」——落库后立即以 ``defer`` 返回，真实决定由解决端点给出。

    ``user_id`` / ``platform_end_user_id`` 恰好一个有值（后台用户对话 vs 嵌入终端
    用户对话），与 ``tool_confirmations`` 的二元主体约束一致。
    """

    def __init__(
        self,
        *,
        session: Any,
        platform_id: int,
        agent_id: int,
        conversation_id_provider: Any,
        user_id: int | None = None,
        platform_end_user_id: int | None = None,
    ) -> None:
        self.session = session
        self.platform_id = platform_id
        self.agent_id = agent_id
        self._conversation_id_provider = conversation_id_provider
        self.user_id = user_id
        self.platform_end_user_id = platform_end_user_id

    async def __call__(self, tool: Any, context: Any) -> ConfirmationDecision | None:
        tool_name = str(getattr(tool, "name", "") or "")
        side_effect = coerce_side_effect(getattr(tool, "side_effect", "none"))
        conversation_id = getattr(self, "_conversation_id_provider")()
        tool_call_id = ""
        if isinstance(context, dict):
            tool_call_id = str(context.get("id") or "")

        # MCP 分支：MCP 自己在 ``invoke_tool`` 里已经落过确认记录（audit + confirmation），
        # 这里不再新建一条，只把它挂起，由解决端点按 ``confirmation_source=mcp`` 续跑。
        mcp_confirmation_id = getattr(context, "confirmation_id", None)
        if mcp_confirmation_id is not None:
            return self._defer(
                tool_name=tool_name,
                tool_type="mcp_tool",
                side_effect=side_effect,
                source=SOURCE_MCP,
                confirmation_id=int(mcp_confirmation_id),
                expires_at=getattr(context, "expires_at", None),
                tool_call_id=tool_call_id,
            )

        # navigation 只影响宿主页面路由、不写数据：交互式运行直通不弹卡。
        if side_effect == "navigation":
            return ConfirmationDecision(
                approved=True,
                reason=NAVIGATION_SIDE_EFFECT,
                message="该工具只影响页面导航，无需确认。",
            )

        if conversation_id is not None:
            remembered = await ToolApprovalService(self.session).remember_check(
                platform_id=self.platform_id,
                conversation_id=int(conversation_id),
                tool_name=tool_name,
                side_effect=side_effect,
            )
            if remembered:
                return ConfirmationDecision(
                    approved=True,
                    reason=REMEMBERED_APPROVAL,
                    message="该工具在本会话中已被批准过，本次直接执行。",
                )

        confirmation = await ToolApprovalService(self.session).request(
            platform_id=self.platform_id,
            agent_id=self.agent_id,
            conversation_id=int(conversation_id) if conversation_id is not None else None,
            tool_name=tool_name,
            tool_type="builtin_tool",
            side_effect=side_effect,
            arguments=self._arguments(context),
            user_id=self.user_id,
            platform_end_user_id=self.platform_end_user_id,
        )
        return self._defer(
            tool_name=tool_name,
            tool_type="builtin_tool",
            side_effect=side_effect,
            source=SOURCE_BUILTIN,
            confirmation_id=confirmation.id,
            expires_at=getattr(confirmation, "expires_at", None),
            tool_call_id=tool_call_id,
        )

    @staticmethod
    def _arguments(context: Any) -> dict:
        if isinstance(context, dict):
            args = context.get("args")
            return args if isinstance(args, dict) else {}
        return {}

    @staticmethod
    def _defer(
        *,
        tool_name: str,
        tool_type: str,
        side_effect: str,
        source: str,
        confirmation_id: int,
        expires_at: Any,
        tool_call_id: str,
    ) -> ConfirmationDecision:
        return ConfirmationDecision(
            approved=False,
            defer=True,
            reason=DEFERRED_FOR_CONFIRMATION,
            message=f"工具 {tool_name} 需要用户确认，已暂停等待你的决定。",
            details={
                "confirmation_id": confirmation_id,
                "confirmation_source": source,
                "tool_name": tool_name,
                "tool_type": tool_type,
                "side_effect": side_effect,
                "tool_call_id": tool_call_id,
                "expires_at": expires_at.isoformat() if expires_at is not None else None,
            },
        )
