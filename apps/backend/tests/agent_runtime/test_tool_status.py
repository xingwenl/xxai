import pytest

from app.modules.agent_runtime.tool_events import normalize_tool_step_status
from app.modules.agent_runtime.contracts import ToolOutcomeStatus


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("confirmation_required", "waiting_confirmation"),
        ("waiting_question", "waiting_question"),
        ("failed", "failed"),
        ("expired", "failed"),
        ("rejected", "failed"),
        ("cancelled", "cancelled"),
        ("budget_exceeded", "budget_exceeded"),
        ("unknown", "failed"),
    ],
)
def test_tool_status_mapping_is_stable(source, expected):
    assert normalize_tool_step_status(source) == expected


def test_tool_outcome_status_contains_request_stop_reasons():
    assert ToolOutcomeStatus.CANCELLED.value == "cancelled"
    assert ToolOutcomeStatus.BUDGET_EXCEEDED.value == "budget_exceeded"
