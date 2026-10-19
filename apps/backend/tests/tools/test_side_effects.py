"""副作用词汇表的单元测试：一套词汇、声明期快速失败、运行期保守回落。"""

from __future__ import annotations

import dataclasses

import pytest

from app.modules.tool_approval.contracts import (
    CONFIRMATION_TTL_SECONDS,
    MEMORY_EXEMPT_SIDE_EFFECTS,
    NO_CONFIRMATION_CHANNEL,
    ConfirmationDecision,
    no_channel_decision,
)
from app.modules.tools.side_effects import (
    SIDE_EFFECT_ORDER,
    SideEffectError,
    coerce_side_effect,
    max_side_effect,
    normalize_side_effect,
    side_effect_rank,
)


def test_normalize_accepts_every_canonical_value() -> None:
    for value in SIDE_EFFECT_ORDER:
        assert normalize_side_effect(value) == value


def test_normalize_is_case_and_whitespace_insensitive() -> None:
    assert normalize_side_effect(" Write ") == "write"
    assert normalize_side_effect("FINANCIAL") == "financial"


def test_normalize_maps_the_legacy_create_alias() -> None:
    """能力层早期的 "create" 与新词汇表的 "write" 是同一个意思。"""

    assert normalize_side_effect("create") == "write"


def test_normalize_treats_blank_as_none() -> None:
    assert normalize_side_effect(None) == "none"
    assert normalize_side_effect("") == "none"
    assert normalize_side_effect("   ") == "none"


def test_normalize_rejects_unknown_values_with_a_locator() -> None:
    with pytest.raises(SideEffectError) as excinfo:
        normalize_side_effect("destructive", where="business tool demo")

    message = str(excinfo.value)
    assert "business tool demo" in message
    assert "destructive" in message


def test_coerce_never_raises_and_falls_back_conservatively() -> None:
    """运行期读侧不能因为声明不合规就崩，也不能静默降级成 none。"""

    assert coerce_side_effect("destructive") == "external"
    assert coerce_side_effect("create") == "write"
    assert coerce_side_effect(None) == "none"


def test_max_side_effect_returns_the_most_conservative_value() -> None:
    assert max_side_effect("none", "write") == "write"
    assert max_side_effect("write", "financial") == "financial"
    assert max_side_effect("external", "navigation") == "external"


def test_max_side_effect_treats_unknown_as_conservative() -> None:
    """包装层声明得再低，也不会盖过未知依赖的保守判定。"""

    assert max_side_effect("none", "bogus") == "external"


def test_max_side_effect_of_nothing_is_none() -> None:
    assert max_side_effect() == "none"
    assert max_side_effect(None, "") == "none"
    assert max_side_effect("", "navigation") == "navigation"


def test_rank_orders_from_least_to_most_conservative() -> None:
    ranks = [side_effect_rank(value) for value in SIDE_EFFECT_ORDER]
    assert ranks == sorted(ranks)
    assert side_effect_rank("none") < side_effect_rank("financial")


def test_no_channel_decision_rejects_with_stable_reason() -> None:
    decision = no_channel_decision("create_task")

    assert decision.approved is False
    assert decision.reason == NO_CONFIRMATION_CHANNEL
    assert "create_task" in decision.message


def test_confirmation_decision_is_immutable() -> None:
    decision = ConfirmationDecision(approved=True)

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.approved = False  # type: ignore[misc]


def test_financial_is_exempt_from_session_memory() -> None:
    """涉及钱的工具每次都要单独批准，不享受会话内记忆。"""

    assert "financial" in MEMORY_EXEMPT_SIDE_EFFECTS
    assert CONFIRMATION_TTL_SECONDS == 600
