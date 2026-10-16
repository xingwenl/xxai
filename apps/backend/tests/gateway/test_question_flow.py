"""ask_user 询问链路的协议与分发测试。"""

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

from app.modules.gateway.connection import validate_incoming_message
from app.modules.gateway.dispatcher import RuntimeToolDispatcher
from app.modules.agent_runtime.events import question_required
from app.modules.gateway.router import (
    _cancel_pending_request_futures,
    _handle_confirmation_resolve,
    _handle_host_tool_result,
    _handle_question_answer,
)
from app.modules.gateway.schemas import ProtocolEnvelope


def _build_dispatcher(
    *,
    event_queue,
    pending_questions,
    question_sequence: int = 0,
):
    dispatcher = RuntimeToolDispatcher(
        session=None,
        context=SimpleNamespace(mcp_tools=[]),
        request_id="req_1",
        agent_id=1,
        platform_id=1,
        end_user_id=1,
        event_queue=event_queue,
        pending_mcp_confirmations={},
        pending_host_results={},
        pending_questions=pending_questions,
        host_tool_repo=None,
    )
    dispatcher.question_sequence = question_sequence
    return dispatcher


def test_question_tool_sends_event_and_returns_user_answer():
    async def scenario():
        event_queue: asyncio.Queue = asyncio.Queue()
        pending_questions: dict[str, asyncio.Future] = {}
        dispatcher = _build_dispatcher(
            event_queue=event_queue, pending_questions=pending_questions
        )

        task = asyncio.create_task(
            dispatcher._invoke_question_tool(
                SimpleNamespace(name="ask_user"),
                {
                    "id": "call_q1",
                    "args": {
                        "question": "如何处理重复订单？",
                        "options": [
                            {"id": "skip", "label": "跳过"},
                            {"id": "merge", "label": "合并"},
                        ],
                        "allowFreeText": True,
                    },
                },
            )
        )
        event = await event_queue.get()
        assert event.type == "question_required"
        # 事件形状即线协议 payload（camell 命名），与 WS 出站一致。
        assert event.payload["questionId"] == "call_q1"
        assert event.payload["question"] == "如何处理重复订单？"
        assert event.payload["options"] == [
            {"id": "skip", "label": "跳过"},
            {"id": "merge", "label": "合并"},
        ]
        assert event.payload["allowFreeText"] is True
        assert event.payload["expiresAt"] is not None

        pending_questions["call_q1"].set_result({"selectedOptionId": "merge"})
        return await task

    outcome = asyncio.run(scenario())
    assert outcome.status == "completed"
    assert outcome.result["answer"] == {"selectedOptionId": "merge"}


def test_question_tool_timeout_returns_expired_answer(monkeypatch):
    monkeypatch.setattr(
        "app.modules.gateway.dispatcher.QUESTION_TIMEOUT_SECONDS", 0.05
    )

    async def scenario():
        event_queue: asyncio.Queue = asyncio.Queue()
        pending_questions: dict[str, asyncio.Future] = {}
        dispatcher = _build_dispatcher(
            event_queue=event_queue, pending_questions=pending_questions
        )
        outcome = await dispatcher._invoke_question_tool(
            SimpleNamespace(name="ask_user"),
            {
                "id": "call_q2",
                "args": {
                    "question": "是否继续？",
                    "options": [
                        {"id": "yes", "label": "是"},
                        {"id": "no", "label": "否"},
                    ],
                },
            },
        )
        return outcome, pending_questions

    outcome, pending_questions = asyncio.run(scenario())
    assert outcome.status == "completed"
    assert outcome.result["answer"]["status"] == "expired"
    assert "call_q2" not in pending_questions


def test_question_tool_respects_per_request_limit():
    async def scenario():
        event_queue: asyncio.Queue = asyncio.Queue()
        dispatcher = _build_dispatcher(
            event_queue=event_queue, pending_questions={}, question_sequence=3
        )
        return await dispatcher._invoke_question_tool(
            SimpleNamespace(name="ask_user"),
            {"id": "call_q3", "args": {"question": "多余的问题？", "options": []}},
        )

    outcome = asyncio.run(scenario())
    assert outcome.status == "completed"
    assert outcome.result["status"] == "unavailable"


def test_question_tool_rejects_invalid_arguments():
    async def scenario():
        event_queue: asyncio.Queue = asyncio.Queue()
        dispatcher = _build_dispatcher(
            event_queue=event_queue, pending_questions={}
        )
        return await dispatcher._invoke_question_tool(
            SimpleNamespace(name="ask_user"), {"id": "call_q4", "args": {}}
        )

    outcome = asyncio.run(scenario())
    assert outcome.status == "failed"
    assert outcome.result["error"]["code"] == "invalid_arguments"


def test_handle_question_answer_wakes_only_matching_future():
    async def scenario():
        future = asyncio.get_running_loop().create_future()
        pending_questions = {"q_1": future}

        # SDK 把入站 requestId 填成问题 ID（sendQuestionAnswer），网关不能拿它
        # 反查聊天请求，否则合法答复会被静默丢弃、模型挂起到超时。
        await _handle_question_answer(
            message={
                "requestId": "q_1",
                "payload": {"questionId": "q_1", "selectedOptionId": "opt_a"},
            },
            pending_questions=pending_questions,
        )
        assert future.done()
        assert future.result() == {"selectedOptionId": "opt_a"}

        # 未知 questionId 与重复提交不破坏其他挂起问题。
        other = asyncio.get_running_loop().create_future()
        pending_questions["q_2"] = other
        await _handle_question_answer(
            message={"payload": {"questionId": "unknown"}},
            pending_questions=pending_questions,
        )
        assert not other.done()
        await _handle_question_answer(
            message={"payload": {"questionId": "q_2", "freeText": "自定义答案"}},
            pending_questions=pending_questions,
        )
        assert other.result() == {"freeText": "自定义答案"}

    asyncio.run(scenario())


def test_handle_question_answer_after_request_cleanup_is_noop():
    """请求取消/结束后容器被清空，迟到的答复只能是 no-op。"""

    async def scenario():
        future = asyncio.get_running_loop().create_future()
        pending_questions = {"q_1": future}
        # 复用 router 在 message_cancel / 断连时对连接级 Future 的真实清理语义。
        _cancel_pending_request_futures(pending_questions)

        await _handle_question_answer(
            message={
                "requestId": "q_1",
                "payload": {"questionId": "q_1", "freeText": "迟到的答复"},
            },
            pending_questions=pending_questions,
        )

        assert future.cancelled()
        assert pending_questions == {}

    asyncio.run(scenario())


def test_inbound_item_id_is_not_used_as_request_filter():
    """回归：入站 requestId 是条目 ID，不能用来过滤请求归属。

    SDK 对 `question_answer` / `confirmation_resolve` / `host_tool_result` 都把
    `requestId` 填成 questionId/callId（websocket.ts）。一旦网关拿它和聊天
    请求 ID 比对，合法回调会被静默丢弃，模型循环挂起到超时。
    """

    for handler in (
        _handle_question_answer,
        _handle_confirmation_resolve,
        _handle_host_tool_result,
    ):
        assert "active_request_id" not in inspect.signature(handler).parameters, (
            f"{handler.__name__} 不得按入站 requestId 过滤请求归属"
        )


def test_question_required_event_uses_protocol_payload():
    """ask_user 的线协议 payload 由事件构造器唯一定义（不再走旧转换表）。"""

    payload = question_required(
        conversation_id=None,
        request_id="req-1",
        question_id="q_1",
        question="选择处理方式",
        description="发现重复订单",
        options=[{"id": "a", "label": "A"}],
        allow_free_text=True,
        require_selection=True,
        expires_at="2026-08-24T12:00:00+00:00",
    ).payload
    assert payload == {
        "questionId": "q_1",
        "question": "选择处理方式",
        "description": "发现重复订单",
        "options": [{"id": "a", "label": "A"}],
        "allowFreeText": True,
        "requireSelection": True,
        "expiresAt": "2026-08-24T12:00:00+00:00",
    }


def test_question_answer_requires_payload():
    with pytest.raises(ValueError):
        validate_incoming_message(
            json.dumps({"type": "question_answer", "requestId": "q_1"})
        )
    parsed = validate_incoming_message(
        json.dumps(
            {
                "type": "question_answer",
                "requestId": "q_1",
                "payload": {"questionId": "q_1", "selectedOptionId": "a"},
            }
        )
    )
    assert parsed["payload"]["selectedOptionId"] == "a"


def test_protocol_envelope_supports_question_required():
    event = ProtocolEnvelope.model_validate(
        {
            "id": "evt_q",
            "type": "question_required",
            "protocolVersion": 1,
            "sequence": 7,
            "timestamp": "2026-08-24T00:00:00Z",
            "payload": {
                "questionId": "q_1",
                "question": "选择处理方式",
                "options": [{"id": "a", "label": "A"}],
                "allowFreeText": True,
            },
        }
    )
    assert event.payload.question_id == "q_1"
    assert event.payload.options[0].label == "A"
