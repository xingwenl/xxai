"""工具确认的跨层契约。

为什么要独立一层：这几个类型被对话分派层（``conversation``）、无人值守策略层
（``tasks``）、内置工具服务层（``builtin_tool``）与网关守卫（``gateway``）共同引用。
放在其中任何一方都会造成反向依赖或循环导入（``tasks`` 曾因此只能在函数体内
延迟导入 ``conversation.tool_dispatch`` 的类型）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# 无确认通道时的稳定原因码：当前运行形态没有任何可以当场问用户的入口
# （REST 流式对话、微信助手非流式通路），或交互式运行的委派子运行不冒泡确认。
NO_CONFIRMATION_CHANNEL = "no_confirmation_channel"

# 兜底原因码：裁决器批准了但调用方仍拿到拒绝（防御性，正常流程不会出现）。
REJECTED_BY_POLICY = "rejected_by_policy"

# 「可被子运行继承」的裁决器标记。只有无人值守策略构造的裁决器带它。
# 委派工具据此决定是否把父运行的裁决器下传：交互式裁决器绑在父会话的连接上，
# 下传等于让确认弹窗冒泡到父会话，本轮明确不做（子运行改为「无确认通道」拒绝）。
INHERITABLE_DECIDER_ATTR = "inheritable_by_delegation"

# 交互式确认的存活时长（秒）。与 MCP 确认保持同一量级：等待期间用户可能已经
# 离开页面，过期后必须留下一条明确的「未执行」记录，而不是无限等待。
CONFIRMATION_TTL_SECONDS = 600

# 会话内确认记忆的批准原因码：同一会话里刚刚批准过同类工具时，后续调用直接复用
# 那次批准，不再重复打扰用户。
REMEMBERED_APPROVAL = "remembered_approval"

# 不参与会话内记忆的副作用：涉及钱的工具每次都必须单独批准。
MEMORY_EXEMPT_SIDE_EFFECTS = frozenset({"financial"})

# navigation 的批准原因码：它只影响宿主页面的路由、不写数据，交互式运行里
# 直通不弹卡（无人值守侧仍由 UnattendedPolicy 决定，因为闸口本身不区分副作用）。
NAVIGATION_SIDE_EFFECT = "navigation_side_effect"

# 用户在确认卡上点了「拒绝」的原因码。
USER_REJECTED = "user_rejected"

# 确认超时（用户始终没有回应）的原因码。与拒绝区分开：拒绝是明确表态，
# 超时可能只是人不在，模型据此选择「换个做法」还是「稍后再试」。
CONFIRMATION_EXPIRED = "confirmation_expired"

# 「已挂起等待确认」的原因码：裁决器把确认记录落库并把运行挂起（REST/SSE 通路），
# 由后续的解决端点续跑，而不是当场拿到批准或拒绝。
DEFERRED_FOR_CONFIRMATION = "deferred_for_confirmation"


@dataclass(frozen=True)
class ConfirmationDecision:
    """一次「是否需要确认」的裁决结果。

    ``message`` 只在拒绝时使用：它会被放进返回给模型的结果里，让模型知道这一步
    为什么没执行。只回一个干巴巴的 rejected 的话，模型容易反复重试同一个操作。

    ``reason`` 是稳定原因码（如 ``strict_approval_allows_navigation_only``、
    ``no_confirmation_channel``），只进工具结果与留痕，用于排障与验证断言。

    ``defer`` 表示「不是拒绝、也不是批准」：确认记录已经落库，本次运行应当就此
    挂起（``confirmation_required``），等解决端点拿到用户的决定后续跑。此时
    ``details`` 携带调用方需要的结构化信息（目前是确认记录主键与过期时间），
    由 ``builtin_tool`` 服务层搬进工具结果的 metadata。
    """

    approved: bool
    message: str = ""
    reason: str = ""
    defer: bool = False
    details: dict[str, Any] | None = None


# 审批裁决回调：返回 None 表示「不由本层处理」，保持默认行为。
# 第二个参数随工具类型而异——MCP 路径是 ToolInvocationOutcome，内置工具路径是
# 调用字典（``{"id": ..., "args": ...}``），页面宿主工具路径是待确认的调用记录。
ConfirmationDecider = Callable[[Any, Any], Awaitable[ConfirmationDecision | None]]


def no_channel_decision(tool_name: str) -> ConfirmationDecision:
    """构造「没有确认通道」的拒绝裁决。

    拒绝而不是放行：本模块存在的前提就是「写工具必须经过批准」，
    在没有入口问用户的通路上静默执行，正是要消除的行为。
    """

    return ConfirmationDecision(
        approved=False,
        reason=NO_CONFIRMATION_CHANNEL,
        message=(
            f"工具 {tool_name} 需要用户确认，但当前通路没有确认入口"
            "（请在支持确认的对话界面里重试）。该操作未执行。"
        ),
    )
