from app.modules.agent_runtime.lifecycle import (
    AgentRunLifecycle,
    RunStatus,
    generation_step_status_for,
    loop_status_for,
    loop_summary_for,
    resolve_result_run_status,
)


def test_lifecycle_allows_only_first_terminal_transition():
    lifecycle = AgentRunLifecycle()

    lifecycle.complete()
    lifecycle.fail({"code": "late-error"})
    lifecycle.cancel()

    assert lifecycle.status is RunStatus.COMPLETED
    assert lifecycle.error is None
    assert lifecycle.finished


def test_lifecycle_records_failure():
    lifecycle = AgentRunLifecycle()
    lifecycle.fail({"code": "provider_error"})

    assert lifecycle.status is RunStatus.FAILED
    assert lifecycle.error == {"code": "provider_error"}


def test_lifecycle_waiting_state_is_resumable_and_terminal_transition_is_idempotent():
    lifecycle = AgentRunLifecycle()

    lifecycle.wait_confirmation()
    assert lifecycle.status is RunStatus.WAITING_CONFIRMATION
    assert not lifecycle.finished

    lifecycle.complete()
    lifecycle.cancel()

    assert lifecycle.status is RunStatus.COMPLETED


def test_lifecycle_budget_is_a_terminal_status():
    lifecycle = AgentRunLifecycle()

    lifecycle.budget_exceeded()
    lifecycle.fail({"code": "late-error"})

    assert lifecycle.status is RunStatus.BUDGET_EXCEEDED
    assert lifecycle.finished


def test_result_status_resolution_is_shared_across_protocol_adapters():
    assert resolve_result_run_status(pending_confirmation_id=7) is RunStatus.WAITING_CONFIRMATION
    assert resolve_result_run_status(budget_exceeded=True) is RunStatus.BUDGET_EXCEEDED
    assert resolve_result_run_status(error={"code": "provider_error"}) is RunStatus.FAILED
    assert resolve_result_run_status() is RunStatus.COMPLETED


def test_finish_field_helpers_preserve_persistence_semantics():
    """RunStatus → 落库字段的矩阵与三个收尾站点既有行为逐字一致。

    数据库 loop/loop_step 只区分“等待用户确认”与非确认收尾两类取值：
    确认等待态分别落 waiting_confirmation / 等待用户确认后继续，其余状态
    （完成、失败、取消、预算等）在协议 Adapter 已提前分流，落库统一收敛为
    succeeded / completed / 已完成回答。该矩阵锁定后，REST/WS 三个收尾
    站点不再各自推导，避免新增等待态时口径漂移。
    """

    waiting = RunStatus.WAITING_CONFIRMATION
    assert generation_step_status_for(waiting) == "waiting_confirmation"
    assert loop_status_for(waiting) == "waiting_confirmation"
    assert loop_summary_for(waiting) == "等待用户确认后继续"

    for status in (
        RunStatus.WAITING_USER,
        RunStatus.WAITING_QUESTION,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.BUDGET_EXCEEDED,
    ):
        assert generation_step_status_for(status) == "succeeded"
        assert loop_status_for(status) == "completed"
        assert loop_summary_for(status) == "已完成回答"
