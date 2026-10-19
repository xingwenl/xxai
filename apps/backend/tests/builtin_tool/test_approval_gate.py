"""内置工具审批闸口：写工具未获批准时 handler 一次都不执行。

闸口位于 ``builtin_tool/services.py::invoke_builtin_tool``：契约校验之后、
handler 之前。这里用最小假仓库与假定义覆盖闸口的五条分支，不连库。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.modules.builtin_tool import services as builtin_services
from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.tool_approval.contracts import (
    NO_CONFIRMATION_CHANNEL,
    ConfirmationDecision,
)

_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


class _EnabledRepo:
    """最低限度的启用状态仓库：闸口只问这一个问题。"""

    async def is_enabled(self, platform_id, agent_id, tool_name) -> bool:
        return True


def _definition(*, name="demo_write", side_effect="write", handler=None):
    return SimpleNamespace(
        name=name,
        description="demo",
        input_schema=_SCHEMA,
        executor=handler,
        side_effect=side_effect,
    )


def _recording_handler(handler_calls):
    async def handler(arguments, ctx):
        handler_calls.append(arguments)
        return {"ok": True}

    return handler


def _invoke(
    monkeypatch,
    definition,
    *,
    decider=None,
    arguments=None,
    caller_tool=None,
):
    monkeypatch.setattr(builtin_services, "get_builtin_tool", lambda _name: definition)
    return asyncio.run(
        invoke_builtin_tool(
            _EnabledRepo(),
            object(),
            tool=caller_tool or SimpleNamespace(name=definition.name),
            call={"args": {"value": "x"} if arguments is None else arguments},
            platform_id=1,
            agent_id=2,
            conversation_id=3,
            user_id=4,
            platform_end_user_id=None,
            session=object(),
            confirmation_decider=decider,
        )
    )


def test_none_side_effect_skips_the_gate_entirely(monkeypatch) -> None:
    """只读工具不该被问：裁决器一次都不该被调用。"""

    calls: list = []
    asked: list = []

    async def decider(tool, call):
        asked.append(tool.name)
        return ConfirmationDecision(approved=False)

    outcome = _invoke(
        monkeypatch,
        _definition(side_effect="none", handler=_recording_handler(calls)),
        decider=decider,
    )

    assert outcome.status == "completed"
    assert calls == [{"value": "x"}]
    assert asked == []


def test_write_tool_without_any_channel_is_rejected(monkeypatch) -> None:
    """没有确认入口时是「拒绝并告知」，不是静默执行。"""

    calls: list = []
    outcome = _invoke(
        monkeypatch,
        _definition(handler=_recording_handler(calls)),
        decider=None,
    )

    assert outcome.status == "rejected"
    assert calls == []
    assert outcome.result["reason"] == NO_CONFIRMATION_CHANNEL
    assert outcome.result["auto_approved"] is False
    assert outcome.result["side_effect"] == "write"
    assert "需要用户确认" in outcome.result["message"]


def test_write_tool_rejected_by_decider_does_not_run_handler(monkeypatch) -> None:
    """策略拒绝时原因码与文案必须原样透出，handler 不得被执行。"""

    calls: list = []

    async def decider(tool, call):
        return ConfirmationDecision(
            approved=False,
            reason="strict_approval_allows_navigation_only",
            message="严格模式只自动批准导航类工具。",
        )

    outcome = _invoke(
        monkeypatch,
        _definition(handler=_recording_handler(calls)),
        decider=decider,
    )

    assert outcome.status == "rejected"
    assert calls == []
    assert outcome.result["reason"] == "strict_approval_allows_navigation_only"
    assert outcome.result["message"] == "严格模式只自动批准导航类工具。"
    assert outcome.result["status"] == "rejected"


def test_write_tool_approved_by_decider_runs_handler(monkeypatch) -> None:
    """批准后照常执行，且 handler 拿到的 arguments 就是调用参数。"""

    calls: list = []

    async def decider(tool, call):
        return ConfirmationDecision(approved=True)

    outcome = _invoke(
        monkeypatch,
        _definition(handler=_recording_handler(calls)),
        decider=decider,
    )

    assert outcome.status == "completed"
    assert calls == [{"value": "x"}]
    assert outcome.result == {"ok": True}


def test_decider_declining_to_handle_is_also_a_rejection(monkeypatch) -> None:
    """裁决器返回 None 表示「不由本层处理」，本层没有别的入口，仍然拒绝。"""

    calls: list = []

    async def decider(tool, call):
        return None

    outcome = _invoke(
        monkeypatch,
        _definition(handler=_recording_handler(calls)),
        decider=decider,
    )

    assert outcome.status == "rejected"
    assert calls == []
    assert outcome.result["reason"] == NO_CONFIRMATION_CHANNEL


def test_invalid_arguments_are_reported_before_asking_the_user(monkeypatch) -> None:
    """契约校验先于弹卡：参数非法时不该打扰用户。"""

    asked: list = []

    async def decider(tool, call):
        asked.append(tool.name)
        return ConfirmationDecision(approved=True)

    outcome = _invoke(
        monkeypatch,
        _definition(handler=_recording_handler([])),
        decider=decider,
        arguments={},
    )

    assert outcome.status == "failed"
    assert outcome.result["error"]["code"] == "invalid_arguments"
    assert asked == []


def test_side_effect_is_read_from_registry_not_from_caller(monkeypatch) -> None:
    """防旁路：调用方传入的 tool 对象自称 none，也不能让写工具绕过闸口。"""

    calls: list = []
    outcome = _invoke(
        monkeypatch,
        _definition(handler=_recording_handler(calls)),
        decider=None,
        caller_tool=SimpleNamespace(name="demo_write", side_effect="none"),
    )

    assert outcome.status == "rejected"
    assert calls == []


def test_decider_receives_the_registry_definition(monkeypatch) -> None:
    """裁决器拿到的是注册表定义（副作用真值来源），不是调用方的对象。"""

    seen: list = []

    async def decider(tool, call):
        seen.append((tool.name, tool.side_effect))
        return ConfirmationDecision(approved=True)

    definition = _definition(handler=_recording_handler([]))
    _invoke(
        monkeypatch,
        definition,
        decider=decider,
        caller_tool=SimpleNamespace(name="demo_write", side_effect="none"),
    )

    assert seen == [("demo_write", "write")]


def test_definition_without_side_effect_attribute_is_treated_as_none(monkeypatch) -> None:
    """向后兼容：老调用点构造的定义没有该字段，按无副作用处理而不是崩掉。"""

    calls: list = []
    definition = SimpleNamespace(
        name="legacy_tool",
        description="legacy",
        input_schema=_SCHEMA,
        executor=_recording_handler(calls),
    )

    outcome = _invoke(monkeypatch, definition)

    assert outcome.status == "completed"
    assert calls == [{"value": "x"}]
