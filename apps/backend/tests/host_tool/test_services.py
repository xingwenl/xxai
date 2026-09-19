from datetime import UTC, datetime, timedelta

import pytest

from app.modules.host_tool.schemas import HostToolPolicyCreate
from app.modules.host_tool.services import (
    allowed_host_tool_names,
    as_utc,
    build_temporary_host_tool_policy,
    transition_status,
    wait_timeout_seconds,
)


def test_as_utc_normalizes_naive_and_aware_database_values():
    """审计时间列两种建表来源都必须能安全参与时间运算。

    alembic 建出的列是 ``TIMESTAMP WITH TIME ZONE``（读回 aware），
    ``create_all`` 建出的列是 naive；两者都要归一到 UTC 后才允许与
    ``datetime.now(UTC)`` 相减，否则直接抛 TypeError。
    """

    naive = datetime(2026, 9, 19, 1, 40, 0)
    aware = datetime(2026, 9, 19, 9, 40, 0, tzinfo=UTC)

    assert as_utc(None) is None
    assert as_utc(naive) == naive.replace(tzinfo=UTC)
    assert as_utc(aware) == aware


def test_wait_timeout_seconds_accepts_both_column_shapes():
    """等待上限计算不能因时间列 naive/aware 差异抛错。"""

    aware = datetime.now(UTC) + timedelta(minutes=10)
    naive = (datetime.now(UTC) + timedelta(minutes=10)).replace(tzinfo=None)

    assert wait_timeout_seconds(None, default=600.0) == 600.0
    assert 590 < wait_timeout_seconds(aware, default=600.0) <= 600
    assert 590 < wait_timeout_seconds(naive, default=600.0) <= 600
    # 已过期的审计按 0 处理，交给 wait_for 立即进入超时分支。
    expired = datetime.now(UTC) - timedelta(seconds=5)
    assert wait_timeout_seconds(expired, default=600.0) == 0.0


def test_policy_requires_object_input_schema_and_valid_tool_name():
    policy = HostToolPolicyCreate(
        name="orders.get_status",
        description="Read order status",
        input_schema={"type": "object", "properties": {"orderId": {"type": "string"}}},
        side_effect="none",
    )
    assert policy.name == "orders.get_status"

    with pytest.raises(ValueError):
        HostToolPolicyCreate(
            name="bad name",
            description="invalid",
            input_schema={"type": "string"},
            side_effect="none",
        )


def test_allowed_host_tool_names_is_three_way_intersection():
    assert allowed_host_tool_names(
        token_names={"weather", "orders.get_status"},
        agent_names={"orders.get_status", "calculator"},
        registered_names={"orders.get_status", "calculator"},
    ) == {"orders.get_status"}


def test_temporary_host_tool_policy_is_held_in_memory():
    policy = build_temporary_host_tool_policy(
        {
            "name": "read_page",
            "description": "Read current page",
            "inputSchema": {"type": "object"},
            "sideEffect": "none",
        }
    )

    assert policy.name == "read_page"
    assert policy.input_schema == {"type": "object"}
    assert policy.side_effect == "none"
    assert policy.confirmation_policy == "auto"


def test_call_status_transition_rejects_duplicate_terminal_result():
    assert transition_status("awaiting_confirmation", "running") == "running"
    assert transition_status("running", "succeeded") == "succeeded"
    with pytest.raises(ValueError):
        transition_status("succeeded", "failed")
