"""host tool 等待超时与取消清理的分发器测试。"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.modules.gateway.dispatcher import RuntimeToolDispatcher
from app.modules.host_tool.services import utc_naive_now


class _Audit:
    """内存审计对象，仅保留 dispatcher 依赖的字段。"""

    def __init__(self, status: str, *, result=None, error=None):
        self.status = status
        self.result = result
        self.error = error
        self.arguments_fingerprint = "fp"
        self.expires_at = utc_naive_now() + timedelta(minutes=10)


class _FakeHostToolRepo:
    """按场景返回审计并记录状态转换的宿主工具仓库替身。"""

    def __init__(self, audit: _Audit, *, short_expiry: bool = False):
        self.audit = audit
        self.short_expiry = short_expiry
        self.created = False
        self.transitions: list[tuple[str, object, object]] = []
        self.get_call_count = 0

    async def get_call(self, call_id, *, platform_id, agent_id, end_user_id):
        self.get_call_count += 1
        if not self.created:
            # 首次调用前没有审计记录，dispatcher 才会走 create_audit 分支。
            return None
        return self.audit

    async def create_audit(self, **values):
        self.created = True
        for key, value in values.items():
            setattr(self.audit, key, value)
        if self.short_expiry:
            # 让超时测试在几十毫秒内完成，而不是等待真实 10 分钟。
            self.audit.expires_at = utc_naive_now() + timedelta(milliseconds=80)
        return self.audit

    async def transition_call(self, audit, target, *, result=None, error=None):
        self.transitions.append((target, result, error))
        audit.status = target
        if result is not None:
            audit.result = result
        if error is not None:
            audit.error = error


def _build_dispatcher(*, repo, pending_host_results):
    return RuntimeToolDispatcher(
        session=None,
        context=SimpleNamespace(mcp_tools=[]),
        request_id="req_1",
        agent_id=1,
        platform_id=1,
        end_user_id=1,
        event_queue=asyncio.Queue(),
        pending_mcp_confirmations={},
        pending_host_results=pending_host_results,
        pending_questions={},
        host_tool_repo=repo,
    )


def test_running_host_tool_times_out_and_transitions_to_failed():
    """页面长时间不回传结果时，running 审计按既有状态机转为 failed。"""

    async def scenario():
        audit = _Audit(status="running")
        repo = _FakeHostToolRepo(audit, short_expiry=True)
        pending: dict[str, asyncio.Future] = {}
        dispatcher = _build_dispatcher(repo=repo, pending_host_results=pending)
        outcome = await dispatcher._invoke_host_tool(
            SimpleNamespace(
                name="page_lookup",
                side_effect="none",
                confirmation_policy="auto",
            ),
            {"id": "call-1", "args": {"q": "x"}},
        )
        return outcome, repo, pending, audit

    outcome, repo, pending, audit = asyncio.run(scenario())

    assert outcome.status == "completed"
    assert outcome.result["code"] == "host_tool_execution_timeout"
    assert outcome.result["error"] == "host_tool_failed"
    assert repo.transitions == [("failed", None, "host_tool_execution_timeout")]
    assert "call-1" not in pending
    assert audit.status == "failed"


def test_awaiting_confirmation_host_tool_times_out_as_expired():
    """确认等待超时按既有状态机转为 expired，而不是 failed。"""

    async def scenario():
        audit = _Audit(status="awaiting_confirmation")
        repo = _FakeHostToolRepo(audit, short_expiry=True)
        pending: dict[str, asyncio.Future] = {}
        dispatcher = _build_dispatcher(repo=repo, pending_host_results=pending)
        outcome = await dispatcher._invoke_host_tool(
            SimpleNamespace(
                name="page_write",
                side_effect="write",
                confirmation_policy="always",
            ),
            {"id": "call-confirm", "args": {}},
        )
        return outcome, repo, pending, audit

    outcome, repo, pending, audit = asyncio.run(scenario())

    assert outcome.result["code"] == "host_tool_expired"
    assert repo.transitions == [("expired", None, None)]
    assert audit.status == "expired"
    assert "call-confirm" not in pending


def test_cancel_while_waiting_host_result_cleans_pending_future():
    """模型 Task 取消时 pending Future 必须被清理，不能留给连接层兜底。"""

    async def scenario():
        audit = _Audit(status="running")
        repo = _FakeHostToolRepo(audit, short_expiry=False)
        pending: dict[str, asyncio.Future] = {}
        dispatcher = _build_dispatcher(repo=repo, pending_host_results=pending)
        task = asyncio.create_task(
            dispatcher._invoke_host_tool(
                SimpleNamespace(
                    name="page_lookup",
                    side_effect="none",
                    confirmation_policy="auto",
                ),
                {"id": "call-cancel", "args": {}},
            )
        )
        # host_tool_call 入队表示 dispatcher 已开始等待页面结果。
        await dispatcher.event_queue.get()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return repo, pending

    repo, pending = asyncio.run(scenario())

    assert "call-cancel" not in pending
    # 取消不允许把审计推进到失败终态，也不生成失败工具结果。
    assert repo.transitions == []


def test_timeout_race_recovers_terminal_result_from_audit():
    """超时与页面成功回调竞争时，从审计终态恢复结果而不是二次转换。"""

    async def scenario():
        audit = _Audit(status="running")

        class RacingRepo(_FakeHostToolRepo):
            async def get_call(self, *args, **kwargs):
                # 第二次读取（超时处理中的复查）模拟页面回调已把审计
                # 推进到 succeeded，此时不能再次执行 failed 转换。
                self.get_call_count += 1
                if not self.created:
                    return None
                if self.get_call_count == 2:
                    return _Audit(status="succeeded", result={"ok": True})
                return audit

        racing_repo = RacingRepo(audit, short_expiry=True)
        pending: dict[str, asyncio.Future] = {}
        dispatcher = _build_dispatcher(
            repo=racing_repo, pending_host_results=pending
        )
        outcome = await dispatcher._invoke_host_tool(
            SimpleNamespace(
                name="page_lookup",
                side_effect="none",
                confirmation_policy="auto",
            ),
            {"id": "call-race", "args": {}},
        )
        return outcome, racing_repo, pending

    outcome, repo, pending = asyncio.run(scenario())

    assert outcome.status == "completed"
    assert outcome.result == {"ok": True}
    assert repo.transitions == []
    assert "call-race" not in pending
