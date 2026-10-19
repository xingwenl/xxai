"""SSE 与 WS 出站事件的形状一致性测试（线协议契约回归）。

两条通道现在共用 ``app.modules.agent_runtime.events``：业务侧与 dispatcher
都产出同一个 ``RunEvent``，SSE 只做 ``to_sse_block``，WS 只做
``json.dumps(to_wire(...))``。本文件用一个事件剧本同时喂两个编码器，并逐条
比对仓库里共享的 golden 文件；``apps/ai-sdk`` 侧的 vitest 用同一份 golden
断言 ``parseProtocolEvent`` 能识别每个事件。
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

from app.modules.gateway.auth import MINIMUM_SDK_VERSION, SERVER_VERSION
from app.modules.agent_runtime.events import (
    PROTOCOL_VERSION,
    build_step_payload,
    confirmation_required,
    host_tool_call,
    message_started,
    pong,
    question_required,
    run_events_from_stream_item,
    session_ready,
    to_sse_block,
    to_wire,
)

ROOT = Path(__file__).resolve().parents[4]
GOLDEN_PATH = ROOT / "apps/ai-sdk/src/core/__tests__/fixtures/run-events.golden.json"

# 固定时间戳，让信封逐字节可比（否则 golden 会因为时间戳漂移而永远不等）。
FIXED_TS = "2026-10-16T00:00:00+00:00"
REQUEST_ID = "req-golden"


def _step(**overrides) -> SimpleNamespace:
    values = {
        "id": 11,
        "sequence": 2,
        "step_type": "model_generation",
        "title": "生成回答",
        "status": "succeeded",
        "input_summary": "用户问：你好",
        "output_summary": "你好，世界",
        "thinking_text": "先打个招呼",
        "tool_name": None,
        "skill_name": None,
        "skill_version": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _stream_items() -> list[dict]:
    """服务层真实产出的流式 item 剧本（形状取自 conversation/services.py）。"""

    conversation = SimpleNamespace(id=101)
    retrieval = _step(
        id=1,
        sequence=1,
        step_type="knowledge_retrieval",
        title="检索知识库",
        output_summary="命中 1 条",
    )
    tool_step = _step(
        id=12,
        sequence=3,
        step_type="builtin",
        title="调用工具：http_get",
        tool_name="http_get",
        input_summary="GET https://example.com",
    )
    result = SimpleNamespace(
        content="你好，世界",
        citations=[{"title": "FAQ", "text": "说明"}],
        knowledge_grounded=True,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        loop_id=1,
    )
    assistant = SimpleNamespace(content_blocks=[{"type": "text", "text": "你好，世界"}])

    return [
        {
            "type": "agent_loop_started",
            "conversation": conversation,
            "payload": {"loopRunId": "1", "status": "running", "summary": "正在处理请求"},
        },
        {
            # 压缩发生在模型调用之前，客户端会在回答增量之前先收到这条事件。
            "type": "context_compacted",
            "conversation": conversation,
            "payload": {
                "ok": True,
                "reason": "compacted",
                "trigger": "auto",
                "tokensBefore": 900,
                "tokensAfter": 120,
                "windowTokens": 1000,
                "percent": 12.0,
                "summaryChars": 42,
            },
        },
        {
            "type": "agent_step_completed",
            "conversation": conversation,
            "payload": build_step_payload(
                retrieval,
                loop_run_id=1,
                sequence=1,
                citation_refs=[{"title": "FAQ", "text": "说明"}],
                with_output=True,
            ),
        },
        {
            "type": "agent_step_started",
            "conversation": conversation,
            "payload": build_step_payload(_step(), loop_run_id=1),
        },
        {"type": "message_delta", "conversation": conversation, "content": "你好"},
        {"type": "message_delta", "conversation": conversation, "content": "，世界"},
        {
            "type": "agent_step_delta",
            "conversation": conversation,
            "payload": {
                "loopRunId": "1",
                "stepId": "11",
                "sequence": 2,
                "stepType": "model_generation",
                "field": "thinking",
                "content": "先打个招呼",
            },
        },
        {
            "type": "agent_step_started",
            "conversation": conversation,
            "payload": build_step_payload(
                tool_step, loop_run_id=1, with_tool=True, with_skill=True
            ),
        },
        {
            "type": "tool_call",
            "conversation": conversation,
            "payload": {
                "tool": "http_get",
                "toolCallId": "call_1",
                "input": "GET https://example.com",
            },
        },
        {
            "type": "tool_result",
            "conversation": conversation,
            "tool": "http_get",
            "tool_type": "builtin",
            "arguments": {"url": "https://example.com"},
            "payload": {"status": "completed", "result": {"status": 200}, "error": None},
        },
        {
            "type": "agent_step_completed",
            "conversation": conversation,
            "payload": build_step_payload(
                tool_step, loop_run_id=1, with_output=True, with_tool=True, with_skill=True
            ),
        },
        {
            "type": "confirmation_required",
            "conversation": conversation,
            "tool": "mcp_pay",
            "tool_type": "mcp_tool",
            "arguments": {"amount": 100, "api_key": "sk-live-123"},
            "payload": {
                "status": "confirmation_required",
                "call_id": "call_2",
                "metadata": {
                    "side_effect": "financial",
                    "expires_at": "2026-10-16T00:10:00+00:00",
                },
            },
        },
        {
            "type": "error",
            "conversation": conversation,
            "payload": {
                "code": "agent_upstream_unavailable",
                "message": "Agent 连接失败（HTTP 502），本轮对话已结束",
                "retryable": True,
            },
        },
        {
            # 每轮模型调用后按 provider 真值上报占用（prompt_tokens）。
            "type": "context_usage",
            "conversation": conversation,
            "payload": {
                "usedTokens": 120,
                "windowTokens": 1000,
                "percent": 12.0,
                "source": "provider",
                "lastCompactedAt": "2026-10-16T00:00:00+00:00",
            },
        },
        {
            "type": "agent_loop_completed",
            "conversation": conversation,
            "payload": {"loopRunId": "1", "status": "completed", "summary": "已完成回答"},
        },
        {
            "type": "completed",
            "conversation": conversation,
            "assistant": assistant,
            "result": result,
        },
    ]

def golden_events() -> list:
    """共享事件剧本：流式 item 派生的事件 + 传输层专属事件。"""

    events = [
        event
        for item in _stream_items()
        for event in run_events_from_stream_item(item, request_id=REQUEST_ID)
    ]
    events.extend(
        [
            message_started(conversation_id=101, request_id=REQUEST_ID),
            # 传输层专属事件也由同一构造器定义，保证 18 种类型只有一个形状来源。
            session_ready(
                payload={
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverVersion": SERVER_VERSION,
                    "minimumSdkVersion": MINIMUM_SDK_VERSION,
                }
            ),
            pong(request_id=REQUEST_ID),
            host_tool_call(
                conversation_id=None,
                request_id=REQUEST_ID,
                call_id="call_3",
                name="navigate_to_page",
                arguments={"page": "bots", "token": "abc"},
                side_effect="navigation",
                requires_confirmation=True,
            ),
            question_required(
                conversation_id=None,
                request_id=REQUEST_ID,
                question_id="q_1",
                question="选择处理方式",
                description="发现重复订单",
                options=[{"id": "skip", "label": "跳过"}],
                allow_free_text=True,
                require_selection=True,
                expires_at="2026-10-16T00:10:00+00:00",
            ),
        ]
    )
    return events


def sse_envelope(event, index: int) -> dict:
    """SSE 编码器：同一批 RunEvent，只多写 event:/data: 行。"""

    block = to_sse_block(event, sequence=index + 1, timestamp=FIXED_TS)
    return json.loads(block.split("data: ", 1)[1].strip())


def ws_envelope(event, index: int) -> dict:
    """WS 编码器：网关把同一批 RunEvent 序列化成 JSON 文本。"""

    return json.loads(
        json.dumps(
            to_wire(event, sequence=index + 1, timestamp=FIXED_TS),
            ensure_ascii=False,
        )
    )


def load_golden() -> list:
    if os.environ.get("UPDATE_RUN_EVENT_GOLDEN") == "1":
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = [
            json.dumps(ws_envelope(event, index), ensure_ascii=False, indent=2)
            for index, event in enumerate(golden_events())
        ]
        GOLDEN_PATH.write_text("[\n" + ",\n".join(encoded) + "\n]\n")
    return json.loads(GOLDEN_PATH.read_text())


def test_sse_and_ws_encoders_match_shared_golden():
    golden = load_golden()
    events = golden_events()

    assert [event.wire_type for event in events] == [item["type"] for item in golden]
    assert [sse_envelope(event, index) for index, event in enumerate(events)] == golden
    assert [ws_envelope(event, index) for index, event in enumerate(events)] == golden


def test_message_completed_payload_is_identical_across_transports():
    golden = [item for item in load_golden() if item["type"] == "message_completed"]
    assert len(golden) == 1
    payload = golden[0]["payload"]
    assert payload["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert payload["knowledgeGrounded"] is True
    assert payload["contentBlocks"] == [{"type": "text", "text": "你好，世界"}]
    assert payload["loop"]["id"] == "1"


def test_tool_payloads_match_sdk_readers():
    """SDK 读 payload.name/input 与 payload.name/result，键名不得回退成蛇形。"""

    golden = {item["type"]: item["payload"] for item in load_golden()}
    assert golden["tool_call"] == {
        "name": "http_get",
        "input": "GET https://example.com",
        "callId": "call_1",
    }
    assert golden["tool_result"] == {
        "name": "http_get",
        "result": {"status": 200},
        "status": "completed",
        "error": None,
    }
    # 确认事件不再泄漏服务层蛇形字段（call_id/expires_at/side_effect）。
    confirmation = golden["confirmation_required"]
    assert "call_id" not in confirmation
    assert confirmation["callId"] == "call_2"
    assert confirmation["sideEffect"] == "financial"
    assert confirmation["summary"]["arguments"]["api_key"] == "[REDACTED]"
    assert golden["host_tool_call"]["arguments"]["token"] == "[REDACTED]"
