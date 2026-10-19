"""③b「解决待确认并续跑同一次运行」的单元测试。

覆盖三块：解决端点的流前校验（归属 / 状态 / 过期 / CAS）、按来源执行挂起的
工具、以及续跑时把工具结果接回上下文快照的语义。真进程的 SSE 全链路由
`tools/harness/verify/2026-10-19-run-confirmation-resume.sh` 覆盖。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.modules.agent_runtime.contracts import ToolOutcome
from app.modules.agent_runtime.error_codes import ErrorCode
from app.modules.conversation import router as router_module
from app.modules.conversation import services as services_module
from app.modules.conversation.schemas import RunResolveRequest
from app.shared.exceptions import ConflictException, NotFoundException


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# 契约与裁决器
# --------------------------------------------------------------------------


def test_run_resolve_request_requires_approved():
    assert RunResolveRequest(approved=False).approved is False
    with pytest.raises(Exception):
        RunResolveRequest()


def test_always_approve_returns_approved_decision():
    decision = _run(router_module._always_approve(SimpleNamespace(name="create_task"), {}))
    assert decision.approved is True
    assert decision.defer is False


# --------------------------------------------------------------------------
# 挂起工具的执行分派
# --------------------------------------------------------------------------


@dataclass
class _Confirmation:
    id: int = 7
    tool_name: str = "create_task"
    arguments: dict = field(default_factory=lambda: {"name": "x"})


class _ToolConfirmationRepo:
    def __init__(self, confirmation):
        self.confirmation = confirmation

    async def get(self, confirmation_id):
        return self.confirmation


class _ApprovalService:
    """记录 resolve 调用顺序，替代真数据库状态机。"""

    calls: list[tuple[int, bool, str]] = []

    def __init__(self, session) -> None:
        pass

    async def resolve(self, *, confirmation_id, approved, actor):
        type(self).calls.append((confirmation_id, approved, actor))
        return SimpleNamespace(status="approved" if approved else "rejected")


def _patch_builtin_execution(monkeypatch, *, confirmation, invocation: dict):
    async def fake_invoke(repo, asset_repo, **kwargs):
        invocation.update(kwargs)
        return SimpleNamespace(
            status="completed",
            result={"task_id": 1},
            metadata={},
            confirmation_id=None,
        )

    monkeypatch.setattr(
        router_module,
        "ToolConfirmationRepository",
        lambda session: _ToolConfirmationRepo(confirmation),
    )
    _ApprovalService.calls = []
    monkeypatch.setattr(router_module, "ToolApprovalService", _ApprovalService)
    monkeypatch.setattr(router_module, "invoke_builtin_tool", fake_invoke)
    monkeypatch.setattr(
        router_module,
        "AssetRepository",
        lambda session: SimpleNamespace(kind="asset"),
    )
    monkeypatch.setattr(
        router_module,
        "BuiltinToolRepository",
        lambda session: SimpleNamespace(kind="builtin"),
    )


def test_execute_pending_tool_builtin_approved_executes_handler(monkeypatch):
    invocation: dict = {}
    _patch_builtin_execution(
        monkeypatch, confirmation=_Confirmation(), invocation=invocation
    )

    outcome = _run(
        router_module._execute_pending_tool(
            object(),
            checkpoint=SimpleNamespace(
                confirmation_source="builtin",
                confirmation_id=7,
                tool_name="create_task",
                tool_call_id="call_7",
            ),
            approved=True,
            agent=SimpleNamespace(id=2, platform_id=1),
            current_user=SimpleNamespace(id=4),
            conversation=SimpleNamespace(id=3),
            loop=SimpleNamespace(id=5),
        )
    )

    assert _ApprovalService.calls == [(7, True, "user")]
    assert invocation["tool"].name == "create_task"
    assert invocation["call"] == {"id": "call_7", "args": {"name": "x"}}
    assert invocation["confirmation_decider"] is router_module._always_approve
    assert isinstance(outcome, ToolOutcome)
    assert outcome.call_id == "call_7"


def test_execute_pending_tool_builtin_rejected_skips_handler(monkeypatch):
    invocation: dict = {}
    _patch_builtin_execution(
        monkeypatch, confirmation=_Confirmation(), invocation=invocation
    )

    outcome = _run(
        router_module._execute_pending_tool(
            object(),
            checkpoint=SimpleNamespace(
                confirmation_source="builtin",
                confirmation_id=7,
                tool_name="create_task",
                tool_call_id="call_7",
            ),
            approved=False,
            agent=SimpleNamespace(id=2, platform_id=1),
            current_user=SimpleNamespace(id=4),
            conversation=SimpleNamespace(id=3),
            loop=SimpleNamespace(id=5),
        )
    )

    assert _ApprovalService.calls == [(7, False, "user")]
    assert invocation == {}
    assert outcome.status == "rejected"
    assert outcome.result["status"] == "rejected"
    assert outcome.call_id == "call_7"


def test_execute_pending_tool_missing_confirmation_conflicts(monkeypatch):
    _patch_builtin_execution(monkeypatch, confirmation=None, invocation={})

    with pytest.raises(ConflictException) as excinfo:
        _run(
            router_module._execute_pending_tool(
                object(),
                checkpoint=SimpleNamespace(
                    confirmation_source="builtin",
                    confirmation_id=7,
                    tool_name="create_task",
                    tool_call_id="call_7",
                ),
                approved=True,
                agent=SimpleNamespace(id=2, platform_id=1),
                current_user=SimpleNamespace(id=4),
                conversation=SimpleNamespace(id=3),
                loop=SimpleNamespace(id=5),
            )
        )
    assert excinfo.value.error_code == ErrorCode.RUN_RESUME_UNAVAILABLE


def test_execute_pending_tool_mcp_delegates_to_mcp_service(monkeypatch):
    seen: dict = {}

    async def fake_resolve(repo, executor, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            status="completed", result={"ok": True}, audit_id=11, confirmation_id=7
        )

    monkeypatch.setattr(
        router_module, "McpRepository", lambda session: SimpleNamespace(kind="mcp")
    )
    monkeypatch.setattr(
        router_module, "RepositoryMcpExecutor", lambda repo: SimpleNamespace()
    )
    monkeypatch.setattr(router_module, "resolve_tool_confirmation", fake_resolve)

    outcome = _run(
        router_module._execute_pending_tool(
            object(),
            checkpoint=SimpleNamespace(
                confirmation_source="mcp",
                confirmation_id=7,
                tool_name="pay",
                tool_call_id="call_mcp",
            ),
            approved=True,
            agent=SimpleNamespace(id=2, platform_id=1),
            current_user=SimpleNamespace(id=4),
            conversation=SimpleNamespace(id=3),
            loop=SimpleNamespace(id=5),
        )
    )

    assert seen["confirmation_id"] == 7
    assert seen["approved"] is True
    assert seen["platform_id"] == 1
    assert outcome.call_id == "call_mcp"


# --------------------------------------------------------------------------
# 解决端点的流前校验
# --------------------------------------------------------------------------


class _FakeCheckpointRepo:
    def __init__(self, checkpoint, *, claim_result=True):
        self.checkpoint = checkpoint
        self.claim_result = claim_result
        self.expired: list[int] = []
        self.claimed: list[tuple[int, str]] = []
        self.consumed: list[int] = []

    async def get_by_loop_run(self, loop_run_id):
        return self.checkpoint

    async def claim(self, loop_run_id, status):
        self.claimed.append((loop_run_id, status))
        return self.claim_result

    async def mark_expired(self, loop_run_id):
        self.expired.append(loop_run_id)

    async def mark_consumed(self, loop_run_id):
        self.consumed.append(loop_run_id)


class _FakeConversationRepo:
    def __init__(self, conversation, loop):
        self.conversation = conversation
        self.loop = loop
        self.saved: list = []

    async def get(self, conversation_id, platform_id, user_id):
        return self.conversation

    async def get_loop(self, loop_id, conversation_id):
        return self.loop

    async def save_loop(self, loop):
        self.saved.append(loop)

    async def list_messages(self, conversation_id):
        return []


def _patch_prepare(monkeypatch, *, checkpoint, conversation, loop, claim_result=True):
    checkpoint_repo = _FakeCheckpointRepo(checkpoint, claim_result=claim_result)
    conversation_repo = _FakeConversationRepo(conversation, loop)
    monkeypatch.setattr(
        router_module,
        "AgentRepository",
        lambda session: SimpleNamespace(
            get_published_agent_for_user=_async_value(
                SimpleNamespace(id=1, platform_id=1)
            )
        ),
    )
    monkeypatch.setattr(
        router_module, "ConversationRepository", lambda session: conversation_repo
    )
    monkeypatch.setattr(
        router_module,
        "AgentLoopRunCheckpointRepository",
        lambda session: checkpoint_repo,
    )
    return checkpoint_repo, conversation_repo


def _async_value(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _pending_checkpoint(**overrides):
    values = {
        "loop_run_id": 5,
        "conversation_id": 3,
        "platform_id": 1,
        "agent_id": 1,
        "user_id": 4,
        "platform_end_user_id": None,
        "status": "pending",
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
        "confirmation_id": 7,
        "confirmation_source": "builtin",
        "tool_name": "create_task",
        "tool_call_id": "call_7",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _prepare(monkeypatch, checkpoint, *, claim_result=True, loop=None):
    conversation = SimpleNamespace(id=3, agent_id=1)
    loop = loop or SimpleNamespace(id=5, status="waiting_confirmation")
    return _patch_prepare(
        monkeypatch,
        checkpoint=checkpoint,
        conversation=conversation,
        loop=loop,
        claim_result=claim_result,
    ), conversation, loop


def test_prepare_resume_not_found_when_not_owned(monkeypatch):
    (checkpoint_repo, _), _, _ = _prepare(
        monkeypatch, _pending_checkpoint(user_id=999)
    )

    with pytest.raises(NotFoundException) as excinfo:
        _run(
            router_module._prepare_resume(
                1,
                5,
                RunResolveRequest(approved=True),
                SimpleNamespace(id=4),
                object(),
            )
        )
    assert excinfo.value.error_code == ErrorCode.RUN_CONFIRMATION_NOT_FOUND
    assert checkpoint_repo.claimed == []


def test_prepare_resume_conflict_when_already_resolved(monkeypatch):
    _prepare(monkeypatch, _pending_checkpoint(status="consumed"))

    with pytest.raises(ConflictException) as excinfo:
        _run(
            router_module._prepare_resume(
                1,
                5,
                RunResolveRequest(approved=True),
                SimpleNamespace(id=4),
                object(),
            )
        )
    assert excinfo.value.error_code == ErrorCode.RUN_CONFIRMATION_ALREADY_RESOLVED


def test_prepare_resume_expired_cancels_loop(monkeypatch):
    (checkpoint_repo, conversation_repo), _, loop = _prepare(
        monkeypatch,
        _pending_checkpoint(expires_at=datetime.now(UTC) - timedelta(seconds=1)),
    )

    with pytest.raises(ConflictException) as excinfo:
        _run(
            router_module._prepare_resume(
                1,
                5,
                RunResolveRequest(approved=True),
                SimpleNamespace(id=4),
                object(),
            )
        )
    assert excinfo.value.error_code == ErrorCode.RUN_CONFIRMATION_EXPIRED
    assert checkpoint_repo.expired == [5]
    assert loop.status == "cancelled"
    assert conversation_repo.saved == [loop]


def test_prepare_resume_conflict_when_claim_lost(monkeypatch):
    (checkpoint_repo, _), _, _ = _prepare(
        monkeypatch, _pending_checkpoint(), claim_result=False
    )

    with pytest.raises(ConflictException) as excinfo:
        _run(
            router_module._prepare_resume(
                1,
                5,
                RunResolveRequest(approved=True),
                SimpleNamespace(id=4),
                object(),
            )
        )
    assert excinfo.value.error_code == ErrorCode.RUN_CONFIRMATION_ALREADY_RESOLVED
    assert checkpoint_repo.claimed == [(5, "resolved")]


# --------------------------------------------------------------------------
# 续跑：把工具结果接回快照
# --------------------------------------------------------------------------


class _FakeRunRepo:
    def __init__(self):
        self.created: list[dict] = []
        self.saved: list = []

    async def list_loop_steps(self, loop_run_id):
        return [SimpleNamespace(sequence=1, tool_call_id="call_7")]

    async def create_loop_step(self, loop_run_id, **values):
        self.created.append(values)
        return SimpleNamespace(id=99, **values)

    async def save_loop(self, loop):
        self.saved.append(loop)


def _drive_resume(monkeypatch, *, context_messages):
    """跑一次 resume_stream_chat，返回它真正喂给模型的消息列表。"""
    captured: dict = {}
    repo = _FakeRunRepo()

    monkeypatch.setattr(services_module, "load_context", lambda payload: context_messages)

    class _Runtime:
        def stream(self, messages, *, request_id=None):
            captured["messages"] = list(messages)
            captured["request_id"] = request_id
            return object()

    monkeypatch.setattr(
        services_module, "build_langchain_runtime", lambda *a, **k: _Runtime()
    )
    monkeypatch.setattr(
        services_module, "stream_runtime_as_conversation", lambda stream: stream
    )

    async def fake_consume(*args, **kwargs):
        captured["tool_steps"] = kwargs["tool_steps"]
        captured["citations"] = kwargs["citations"]
        yield {"type": "message_delta", "text": "ok"}

    monkeypatch.setattr(services_module, "_consume_agent_events", fake_consume)

    async def scenario():
        items = [
            item
            async for item in services_module.resume_stream_chat(
                repo,
                SimpleNamespace(
                    version=SimpleNamespace(),
                    builtin_tools=(),
                    mcp_tools=(),
                    skill_script_tools=(),
                    skill_instruction_tool=None,
                ),
                conversation=SimpleNamespace(id=3),
                loop=SimpleNamespace(id=5, request_id="req-5"),
                checkpoint=SimpleNamespace(context=[{"kind": "message"}]),
                outcome=ToolOutcome(
                    status="completed",
                    result={"task_id": 1},
                    call_id="call_7",
                ),
                model=SimpleNamespace(model_name="stub-model-x"),
                citations=[{"title": "t"}],
            )
        ]
        return items

    return _run(scenario()), captured, repo


def test_resume_stream_chat_replaces_pending_tool_outcome(monkeypatch):
    pending = ToolOutcome(status="confirmation_required", call_id="call_7")
    items, captured, repo = _drive_resume(
        monkeypatch, context_messages=["hello", "assistant", pending]
    )

    assert [item["type"] for item in items] == ["message_delta"]
    messages = captured["messages"]
    # 同一 call_id 只能有一条工具结果：末位是被替换而不是被追加。
    assert len(messages) == 3
    assert messages[-1].status == "completed"
    assert messages[-1].call_id == "call_7"
    assert captured["request_id"] == "req-5"
    # 新生成步骤的 sequence 接在既有步骤之后，历史步骤按 call_id 复用。
    assert repo.created[0]["sequence"] == 2
    assert repo.created[0]["title"] == "继续生成回答"
    assert set(captured["tool_steps"]) == {"call_7"}


def test_resume_stream_chat_appends_when_last_is_not_tool_outcome(monkeypatch):
    _, captured, _ = _drive_resume(
        monkeypatch, context_messages=["hello", "assistant"]
    )

    messages = captured["messages"]
    assert len(messages) == 3
    assert messages[-1].status == "completed"


# --------------------------------------------------------------------------
# 检查点写入
# --------------------------------------------------------------------------


class _CheckpointWriter:
    def __init__(self, stored):
        self.stored = stored

    async def create(self, **values):
        self.stored.append(values)
        return SimpleNamespace(id=1, **values)


def _writer():
    return services_module._RunCheckpointWriter(
        repo=SimpleNamespace(session=object()),
        platform_id=1,
        agent_id=1,
        user_id=4,
    )


def _patch_checkpoint_writer(monkeypatch):
    stored: list[dict] = []
    monkeypatch.setattr(
        services_module,
        "AgentLoopRunCheckpointRepository",
        lambda session: _CheckpointWriter(stored),
    )
    monkeypatch.setattr(
        services_module, "dump_context", lambda messages: [{"kind": "text"}]
    )
    return stored


def test_write_run_checkpoint_skips_incomplete_payload(monkeypatch):
    stored = _patch_checkpoint_writer(monkeypatch)
    outcome = ToolOutcome(status="confirmation_required", confirmation_id=7, call_id="c")

    _run(
        services_module._write_run_checkpoint(
            _writer(),
            SimpleNamespace(id=3),
            SimpleNamespace(id=5),
            {"pending_context": None, "tool_call_id": "c"},
            outcome,
        )
    )
    assert stored == []


def test_write_run_checkpoint_marks_mcp_source(monkeypatch):
    stored = _patch_checkpoint_writer(monkeypatch)
    outcome = ToolOutcome(
        status="confirmation_required",
        confirmation_id=7,
        audit_id=11,
        call_id="call_7",
        metadata={"side_effect": "write"},
    )

    _run(
        services_module._write_run_checkpoint(
            _writer(),
            SimpleNamespace(id=3),
            SimpleNamespace(id=5),
            {
                "pending_context": ["snapshot"],
                "tool_call_id": "call_7",
                "tool": "pay",
                "tool_type": "mcp_tool",
            },
            outcome,
        )
    )

    assert len(stored) == 1
    written = stored[0]
    assert written["confirmation_source"] == "mcp"
    assert written["confirmation_id"] == 7
    assert written["loop_run_id"] == 5
    assert written["conversation_id"] == 3
    assert written["tool_name"] == "pay"
    assert written["side_effect"] == "write"
    assert written["context"] == [{"kind": "text"}]
    assert written["expires_at"] > datetime.now(UTC)


# --------------------------------------------------------------------------
# 快照序列化：轮次元数据里的 pending_context 是快照自身，必须被剔除
# --------------------------------------------------------------------------


def test_dump_context_drops_self_nested_pending_context():
    """回归：`AgentLoop` 会把快照塞进 `last_turn.metadata["pending_context"]`。

    而该轮本身也在快照里，于是元数据里嵌着活对象列表；真进程上曾因此
    抛 `TypeError: Object of type ToolOutcome is not JSON serializable`，
    让挂起那刻的整轮请求以 `agent_request_failed` 收尾。
    """

    import json

    from app.modules.agent_runtime.contracts import ToolCall
    from app.modules.agent_runtime.langchain_adapter import dump_context, load_context
    from app.modules.agent_runtime.loop import ModelTurn

    outcome = ToolOutcome(
        status="confirmation_required",
        result={"status": "confirmation_required"},
        call_id="call_9",
        confirmation_id=9,
        metadata={"side_effect": "write", "expires_at": "2026-10-19T00:00:00+00:00"},
    )
    turn = ModelTurn(
        content="",
        tool_calls=[
            ToolCall(
                id="call_9",
                name="create_task",
                arguments={"name": "x"},
                tool_type="builtin_tool",
            )
        ],
        metadata={"usage": {"prompt_tokens": 5}},
    )
    context = [turn, outcome]
    turn.metadata["pending_context"] = context

    dumped = dump_context(context)

    assert json.dumps(dumped, ensure_ascii=False)
    assert [entry["kind"] for entry in dumped] == ["model_turn", "tool_outcome"]
    assert dumped[0]["metadata"] == {"usage": {"prompt_tokens": 5}}
    assert dumped[1]["metadata"]["side_effect"] == "write"
    restored = load_context(dumped)
    assert [type(item).__name__ for item in restored] == ["ModelTurn", "ToolOutcome"]
    assert restored[1].confirmation_id == 9


def test_dump_context_survives_non_json_metadata():
    """工具在 metadata 里塞了非 JSON 值时，落检查点不能失败（退化成字符串）。"""

    from app.modules.agent_runtime.contracts import ToolOutcome
    from app.modules.agent_runtime.langchain_adapter import dump_context

    marker = object()
    outcome = ToolOutcome(
        status="confirmation_required",
        result={"opaque": marker},
        call_id="call_10",
        confirmation_id=10,
        metadata={"marker": marker},
    )

    dumped = dump_context([outcome])

    assert dumped[0]["kind"] == "tool_outcome"
    assert isinstance(dumped[0]["metadata"]["marker"], str)
    assert isinstance(dumped[0]["result"]["opaque"], str)
