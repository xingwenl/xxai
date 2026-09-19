"""无人值守审批策略单元测试。

三条规则互相正交，这里逐条锁定，避免以后调参时改坏边界：
financial 一律不批准、严格模式只批 navigation、auto_approve=false 全拒。
"""

from __future__ import annotations

from app.modules.tasks.unattended import (
    UnattendedPolicy,
    build_confirmation_decider,
)


def test_default_policy_approves_non_financial() -> None:
    """默认策略：非 financial 的确认请求自动批准。"""

    policy = UnattendedPolicy()
    for effect in ("navigation", "write", "external", "none", None):
        approved, reason = policy.decide(effect)
        assert approved is True, effect
        assert reason == "auto_approved"


def test_financial_is_never_auto_approved() -> None:
    """financial 类操作在任何配置下都不自动批准。"""

    for auto_approve in (True, False):
        for strict in (True, False):
            policy = UnattendedPolicy(
                auto_approve=auto_approve, strict_approval=strict
            )
            approved, reason = policy.decide("financial")
            assert approved is False
            assert reason == "financial_side_effect_not_auto_approved"


def test_auto_approve_disabled_rejects_everything() -> None:
    """关闭自动批准后，连 navigation 也不批。"""

    policy = UnattendedPolicy(auto_approve=False)
    for effect in ("navigation", "write", "external", "financial"):
        approved, _ = policy.decide(effect)
        assert approved is False


def test_strict_approval_allows_navigation_only() -> None:
    """严格模式：只有 navigation 自动批准，其余拒绝。"""

    policy = UnattendedPolicy(strict_approval=True)
    approved, reason = policy.decide("navigation")
    assert approved is True
    assert reason == "auto_approved"

    for effect in ("write", "external", "none"):
        approved, reason = policy.decide(effect)
        assert approved is False, effect
        assert reason == "strict_approval_allows_navigation_only"


def test_side_effect_is_normalized() -> None:
    """side_effect 大小写与空白不应影响判定。"""

    policy = UnattendedPolicy()
    approved, reason = policy.decide("  FINANCIAL  ")
    assert approved is False
    assert reason == "financial_side_effect_not_auto_approved"


def test_approved_count_only_counts_approvals() -> None:
    """只有批准才计入 auto_approved_count。"""

    policy = UnattendedPolicy()
    for name, effect in (
        ("a", "write"),
        ("b", "financial"),
        ("c", "navigation"),
    ):
        approved, reason = policy.decide(effect)
        policy.record(name, effect, approved, reason)
    assert policy.approved_count == 2
    assert len(policy.decisions) == 3


def test_decisions_are_traceable() -> None:
    """每次决策都留痕：工具名、副作用、是否批准、原因。"""

    policy = UnattendedPolicy(strict_approval=True)
    approved, reason = policy.decide("write")
    policy.record("send_sms", "write", approved, reason)

    entry = policy.decisions[0]
    assert entry["tool"] == "send_sms"
    assert entry["side_effect"] == "write"
    assert entry["approved"] is False
    assert entry["reason"] == "strict_approval_allows_navigation_only"


def test_skipped_result_is_explicit_failure() -> None:
    """跳过结果必须是明确失败语义，且包含原因，模型据此可调整。"""

    policy = UnattendedPolicy()
    result = policy.skipped_result("pay_now", "financial_side_effect_not_auto_approved")
    assert result["status"] == "rejected"
    assert result["auto_approved"] is False
    assert result["reason"] == "financial_side_effect_not_auto_approved"
    assert "pay_now" in result["message"]


def test_build_confirmation_decider_returns_decision_and_records() -> None:
    """回调返回裁决对象并累计计数，供工具分派层直接使用。"""

    import asyncio
    from types import SimpleNamespace

    policy = UnattendedPolicy()
    decider = build_confirmation_decider(policy)

    async def run():
        tool = SimpleNamespace(name="page_jump", side_effect="navigation")
        return await decider(tool, None)

    decision = asyncio.run(run())
    assert decision.approved is True
    assert decision.message == ""
    assert policy.approved_count == 1
    assert policy.decisions[0]["tool"] == "page_jump"


def test_build_confirmation_decider_explains_rejection() -> None:
    """拒绝时裁决对象必须带说明，供分派层回传给模型。"""

    import asyncio
    from types import SimpleNamespace

    policy = UnattendedPolicy()
    decider = build_confirmation_decider(policy)

    async def run():
        tool = SimpleNamespace(name="pay_now", side_effect="financial")
        return await decider(tool, None)

    decision = asyncio.run(run())
    assert decision.approved is False
    assert "pay_now" in decision.message
    assert "financial_side_effect_not_auto_approved" in decision.message
    assert policy.approved_count == 0
