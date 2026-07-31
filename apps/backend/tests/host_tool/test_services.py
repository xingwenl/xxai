import pytest

from app.modules.host_tool.schemas import HostToolPolicyCreate
from app.modules.host_tool.services import (
    allowed_host_tool_names,
    build_temporary_host_tool_policy,
    transition_status,
    utc_naive_now,
)


def test_database_timestamp_is_utc_and_timezone_naive():
    value = utc_naive_now()

    assert value.tzinfo is None


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
