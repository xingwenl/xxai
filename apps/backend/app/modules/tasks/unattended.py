"""无人值守运行的审批策略。

任务到点后在后台跑一轮 Agent，没有人当场点「确认」。这一层负责回答
一个问题：**这次需要确认的工具调用，批还是不批？**

规则（与 spec 一致）：
- ``auto_approve=false``：一律不自动批准，全部拒绝并留痕；
- ``side_effect="financial"``：一律不批准（不可逆操作必须有人把关），
  无论 ``auto_approve`` 与严格模式怎么配；
- ``strict_approval=true``：只自动批准 ``side_effect="navigation"``
  的工具（纯页面跳转类），其余拒绝；
- 其余情况：自动批准。

所有「跳过」都返回明确的工具结果，让模型据此调整后续动作，
而不是让它以为调用成功了。批准次数会累计到 ``auto_approved_count``，
和执行记录一起构成「哪条任务的哪次运行批准了什么」的追溯链路。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 一律不自动批准的副作用类型：支付/扣款等不可逆操作。
NEVER_AUTO_APPROVE_SIDE_EFFECTS = frozenset({"financial"})
# 严格模式下唯一允许自动批准的副作用类型。
STRICT_MODE_ALLOWED_SIDE_EFFECTS = frozenset({"navigation"})


@dataclass
class UnattendedPolicy:
    """一次无人值守运行的审批策略。"""

    auto_approve: bool = True
    strict_approval: bool = False
    # 累计自动批准次数，运行结束后写回 task_runs.auto_approved_count
    approved_count: int = 0
    # 决策留痕，便于排障与验证（工具名 + 决定 + 原因）
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def decide(self, side_effect: str | None) -> tuple[bool, str]:
        """裁决一次需要确认的工具调用。

        返回 ``(approved, reason)``；``reason`` 会写进工具结果与决策留痕。
        """

        effect = (side_effect or "none").strip().lower()

        if effect in NEVER_AUTO_APPROVE_SIDE_EFFECTS:
            return False, "financial_side_effect_not_auto_approved"
        if not self.auto_approve:
            return False, "auto_approve_disabled"
        if self.strict_approval and effect not in STRICT_MODE_ALLOWED_SIDE_EFFECTS:
            return False, "strict_approval_allows_navigation_only"
        return True, "auto_approved"

    def record(self, tool_name: str, side_effect: str | None, approved: bool, reason: str) -> None:
        """记录一次决策并维护自动批准计数。"""

        if approved:
            self.approved_count += 1
        self.decisions.append(
            {
                "tool": tool_name,
                "side_effect": side_effect or "none",
                "approved": approved,
                "reason": reason,
            }
        )

    def skipped_result(self, tool_name: str, reason: str) -> dict[str, Any]:
        """被跳过时返回给模型的工具结果。

        必须是明确的失败语义：模型据此知道这一步没执行，
        从而调整计划，而不是当作成功继续往下走。
        """

        return {
            "status": "rejected",
            "auto_approved": False,
            "reason": reason,
            "message": (
                f"无人值守运行时不会自动批准工具 {tool_name}（原因：{reason}）；"
                "该操作未执行，请改用其他方式完成任务，或让用户手动运行。"
            ),
        }


def build_confirmation_decider(policy: UnattendedPolicy):
    """构造注入给工具分派层的审批回调。

    本层不做等待——无人值守场景没有人可以回答，所以「需要确认」在这里
    必须被立刻裁决成批准或拒绝。拒绝时带上说明文本，让模型知道原因。
    """

    from app.modules.conversation.tool_dispatch import ConfirmationDecision

    async def decide(tool, outcome) -> ConfirmationDecision:
        side_effect = getattr(tool, "side_effect", None)
        tool_name = getattr(tool, "name", "unknown")
        approved, reason = policy.decide(side_effect)
        policy.record(tool_name, side_effect, approved, reason)
        if approved:
            return ConfirmationDecision(approved=True)
        return ConfirmationDecision(
            approved=False,
            message=policy.skipped_result(tool_name, reason)["message"],
        )

    return decide
