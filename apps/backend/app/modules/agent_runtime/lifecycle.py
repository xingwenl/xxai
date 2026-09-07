"""Agent 请求生命周期状态机。"""

from enum import StrEnum


class RunStatus(StrEnum):
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    WAITING_USER = "waiting_user"
    WAITING_QUESTION = "waiting_question"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"


def resolve_result_run_status(
    *,
    pending_confirmation_id: int | None = None,
    pending_user_input: bool = False,
    pending_question: bool = False,
    budget_exceeded: bool = False,
    error: dict | None = None,
) -> RunStatus:
    """根据统一结果元数据解析请求状态，供 REST/WS Adapter 共用。

    判断顺序固定为等待态、预算终态、失败终态、成功终态；这样协议层不会
    因为各自排列条件不同而产生不同 loop 状态。等待态优先于预算/错误，
    因为它代表请求仍可 continuation 恢复。
    """

    if pending_confirmation_id is not None:
        return RunStatus.WAITING_CONFIRMATION
    if pending_question:
        return RunStatus.WAITING_QUESTION
    if pending_user_input:
        return RunStatus.WAITING_USER
    if budget_exceeded:
        return RunStatus.BUDGET_EXCEEDED
    if error is not None:
        return RunStatus.FAILED
    return RunStatus.COMPLETED


# DB loop / loop_step 的合法落库状态与 RunStatus 全量集合不是一一对应：
# 非等待确认的完成、失败、取消、预算等终态在协议 Adapter 中已由
# resolve_result_run_status 提前分流，落库统一收敛为“非确认等待”两类值。
# 因此下面三个助手只区分 WAITING_CONFIRMATION 与其他状态，逐字保留三个
# 收尾站点既有行为，避免把状态口径扩散到各 REST/WS Adapter。
def generation_step_status_for(result_status: RunStatus) -> str:
    """把请求终态映射为 model_generation 步骤落库状态。"""

    return (
        "waiting_confirmation"
        if result_status is RunStatus.WAITING_CONFIRMATION
        else "succeeded"
    )


def loop_status_for(result_status: RunStatus) -> str:
    """把请求终态映射为 loop 落库状态。"""

    return (
        "waiting_confirmation"
        if result_status is RunStatus.WAITING_CONFIRMATION
        else "completed"
    )


def loop_summary_for(result_status: RunStatus) -> str:
    """把请求终态映射为 loop 摘要文案。"""

    return (
        "等待用户确认后继续"
        if result_status is RunStatus.WAITING_CONFIRMATION
        else "已完成回答"
    )


class AgentRunLifecycle:
    """保证请求只能从运行态进入一个明确终态。"""

    def __init__(self) -> None:
        self.status = RunStatus.RUNNING
        self.error: dict | None = None

    @property
    def finished(self) -> bool:
        return self.status not in {
            RunStatus.RUNNING,
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.WAITING_USER,
            RunStatus.WAITING_QUESTION,
        }

    def wait_confirmation(self) -> None:
        self._wait(RunStatus.WAITING_CONFIRMATION)

    def wait_user(self) -> None:
        self._wait(RunStatus.WAITING_USER)

    def wait_question(self) -> None:
        self._wait(RunStatus.WAITING_QUESTION)

    def complete(self) -> None:
        self._finish(RunStatus.COMPLETED)

    def fail(self, error: dict) -> None:
        if self.finished:
            return
        self.error = error
        self._finish(RunStatus.FAILED)

    def cancel(self) -> None:
        self._finish(RunStatus.CANCELLED)

    def budget_exceeded(self) -> None:
        self._finish(RunStatus.BUDGET_EXCEEDED)

    def _wait(self, status: RunStatus) -> None:
        if self.finished:
            return
        self.status = status

    def _finish(self, status: RunStatus) -> None:
        if self.finished:
            return
        self.status = status
