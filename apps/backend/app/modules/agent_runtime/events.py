"""ai-agent.v1 运行事件模型：出站事件形状的唯一来源。

REST SSE 与 Embed WebSocket 共享同一批 ``RunEvent`` 构造器与 ``to_wire()``：
事件类型字面量、payload 键名（驼峰）与信封字段只在本文件定义一次，两条传输
各自只负责编码——SSE 把信封写成 ``event:`` / ``data:`` 文本行，WebSocket
直接发 JSON 文本。transport 专属事件（``session_ready`` / ``pong``）同样在
本文件声明，由传输层决定何时发出。

本模块不依赖 ``conversation``：它只依赖 stdlib、``agent_runtime.contracts``
与 ``host_tool.services.redact_sensitive``，避免与 conversation 形成循环 import。
``build_step_payload`` 与 ``format_sse_event`` 历史上住在
``conversation/runtime.py``，这里下沉为唯一定义处，原模块按原路径再导出。

新增协议事件时只在本文件注册；传输层不得出现事件类型字面量。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.modules.host_tool.services import redact_sensitive

# 线协议版本：与 apps/ai-sdk/src/core/protocol.ts 的 PROTOCOL_VERSION 对齐。
PROTOCOL_VERSION = 1


class RunEventType(StrEnum):
    """线协议事件类型，与 SDK ``ProtocolEventType`` 的联合类型一一对应。"""

    SESSION_READY = "session_ready"
    MESSAGE_STARTED = "message_started"
    MESSAGE_DELTA = "message_delta"
    CITATION = "citation"
    MESSAGE_COMPLETED = "message_completed"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    HOST_TOOL_CALL = "host_tool_call"
    CONFIRMATION_REQUIRED = "confirmation_required"
    QUESTION_REQUIRED = "question_required"
    ERROR = "error"
    PONG = "pong"
    AGENT_LOOP_STARTED = "agent_loop_started"
    AGENT_STEP_STARTED = "agent_step_started"
    AGENT_STEP_DELTA = "agent_step_delta"
    AGENT_STEP_COMPLETED = "agent_step_completed"
    AGENT_LOOP_COMPLETED = "agent_loop_completed"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class RunEvent:
    """一次运行产生的线协议事件（尚未附加 sequence / 时间戳）。"""

    type: RunEventType | str
    payload: dict[str, Any] = field(default_factory=dict)
    conversation_id: int | str | None = None
    request_id: str | None = None

    @property
    def wire_type(self) -> str:
        """线协议里的 ``type`` 字符串；StrEnum 必须显式取值才能参与序列化。"""

        return str(self.type)


def to_wire(
    event: RunEvent,
    *,
    sequence: int,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """把 RunEvent 编码为线协议信封（SDK ``ProtocolEvent`` 的形状）。"""

    value: dict[str, Any] = {
        "id": event_id or f"evt_{sequence}",
        "type": event.wire_type,
        "protocolVersion": PROTOCOL_VERSION,
        "sequence": sequence,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "payload": event.payload,
    }
    if event.conversation_id is not None:
        value["conversationId"] = str(event.conversation_id)
    if event.request_id is not None:
        value["requestId"] = event.request_id
    return value


def format_sse_event(event: dict[str, Any]) -> str:
    """把线协议信封格式化为一个 SSE 文本块。

    SSE 格式为 ``event: <类型>\\ndata: <JSON>\\n\\n``；入参必须是
    ``to_wire()`` 的产物（信封），不是裸 payload。
    """

    return (
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def to_sse_block(
    event: RunEvent,
    *,
    sequence: int,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> str:
    """RunEvent -> SSE 文本块，与 WS 的 ``json.dumps(to_wire(...))`` 同源。"""

    return format_sse_event(
        to_wire(event, sequence=sequence, event_id=event_id, timestamp=timestamp)
    )


# ---------------------------------------------------------------------------
# 出站事件构造：业务侧直接产出 RunEvent
# ---------------------------------------------------------------------------


def message_started(*, conversation_id: int | None, request_id: str) -> RunEvent:
    """请求已被接受的通知事件，payload 为空对象。"""

    return RunEvent(
        type=RunEventType.MESSAGE_STARTED,
        payload={},
        conversation_id=conversation_id,
        request_id=request_id,
    )


def message_delta(
    *, conversation_id: int | None, request_id: str, content: str
) -> RunEvent:
    """模型增量正文。"""

    return RunEvent(
        type=RunEventType.MESSAGE_DELTA,
        payload={"content": content},
        conversation_id=conversation_id,
        request_id=request_id,
    )


def citation(
    *, conversation_id: int | None, request_id: str, citation: dict
) -> RunEvent:
    """知识库引用，payload 直接透传 citation。"""

    return RunEvent(
        type=RunEventType.CITATION,
        payload=citation,
        conversation_id=conversation_id,
        request_id=request_id,
    )


def _loop_payload(loop) -> dict:
    """agent_loop_* 事件共用的 payload 结构。"""

    return {
        "loopRunId": str(loop.id),
        "status": loop.status,
        "summary": loop.summary,
    }


def agent_loop_started(
    *, conversation_id: int | None, request_id: str, loop
) -> RunEvent:
    return RunEvent(
        type=RunEventType.AGENT_LOOP_STARTED,
        payload=_loop_payload(loop),
        conversation_id=conversation_id,
        request_id=request_id,
    )


def agent_loop_completed(
    *, conversation_id: int | None, request_id: str, loop
) -> RunEvent:
    return RunEvent(
        type=RunEventType.AGENT_LOOP_COMPLETED,
        payload=_loop_payload(loop),
        conversation_id=conversation_id,
        request_id=request_id,
    )


def agent_step_started(
    *,
    conversation_id: int | None,
    request_id: str,
    loop,
    step,
    **payload_kwargs,
) -> RunEvent:
    """agent_step_started 事件，payload 由 build_step_payload 构造。"""

    return RunEvent(
        type=RunEventType.AGENT_STEP_STARTED,
        payload=build_step_payload(step, loop_run_id=loop.id, **payload_kwargs),
        conversation_id=conversation_id,
        request_id=request_id,
    )


def agent_step_completed(
    *,
    conversation_id: int | None,
    request_id: str,
    loop,
    step,
    **payload_kwargs,
) -> RunEvent:
    """agent_step_completed 事件，payload 由 build_step_payload 构造。"""

    return RunEvent(
        type=RunEventType.AGENT_STEP_COMPLETED,
        payload=build_step_payload(step, loop_run_id=loop.id, **payload_kwargs),
        conversation_id=conversation_id,
        request_id=request_id,
    )


def agent_step_delta(
    *,
    conversation_id: int | None,
    request_id: str,
    loop,
    step,
    field: str,
    content: str,
) -> RunEvent:
    """模型生成过程中的增量事件（如 thinking 流）。"""

    return RunEvent(
        type=RunEventType.AGENT_STEP_DELTA,
        payload={
            "loopRunId": str(loop.id),
            "stepId": str(step.id),
            "sequence": step.sequence,
            "stepType": step.step_type,
            "field": field,
            "content": content,
        },
        conversation_id=conversation_id,
        request_id=request_id,
    )


def message_completed(
    *,
    conversation_id: int | None,
    request_id: str,
    result,
    content: str,
    content_blocks: list,
    loop_run_id=None,
) -> RunEvent:
    """最终回答事件，payload 组装最终状态、用量与 loop 摘要。"""

    return RunEvent(
        type=RunEventType.MESSAGE_COMPLETED,
        payload={
            "content": content,
            "contentBlocks": content_blocks,
            "citations": result.citations,
            "knowledgeGrounded": result.knowledge_grounded,
            "usage": result.usage,
            "loop": (
                {
                    "id": str(loop_run_id),
                    "requestId": request_id,
                    "status": "completed",
                    "summary": "已完成回答",
                    "steps": [],
                }
                if loop_run_id
                else None
            ),
        },
        conversation_id=conversation_id,
        request_id=request_id,
    )


def error(
    *,
    request_id: str | None,
    payload: dict,
    conversation_id: int | None = None,
) -> RunEvent:
    """错误事件，payload 为稳定的可展示错误结构。"""

    return RunEvent(
        type=RunEventType.ERROR,
        payload=payload,
        conversation_id=conversation_id,
        request_id=request_id,
    )


def tool_call(
    *,
    conversation_id: int | None,
    request_id: str | None,
    name: str,
    tool_input: Any = None,
    call_id: str | None = None,
) -> RunEvent:
    """模型发起工具调用的通知事件（SDK 读取 ``payload.name`` / ``payload.input``）。"""

    return RunEvent(
        type=RunEventType.TOOL_CALL,
        payload={"name": name, "input": tool_input, "callId": call_id},
        conversation_id=conversation_id,
        request_id=request_id,
    )


def tool_result(
    *,
    conversation_id: int | None,
    request_id: str | None,
    name: str,
    result: Any = None,
    status: str | None = None,
    error_payload: Any = None,
) -> RunEvent:
    """工具执行结果事件（SDK 读取 ``payload.name`` / ``payload.result``）。"""

    return RunEvent(
        type=RunEventType.TOOL_RESULT,
        payload={
            "name": name,
            "result": result,
            "status": status,
            "error": error_payload,
        },
        conversation_id=conversation_id,
        request_id=request_id,
    )


def host_tool_call(
    *,
    conversation_id: int | None = None,
    request_id: str | None,
    call_id: str | None,
    name: str,
    arguments: Any,
    side_effect: str | None,
    requires_confirmation: bool,
) -> RunEvent:
    """页面宿主工具调用事件：要求宿主页面执行并把结果回传。"""

    return RunEvent(
        type=RunEventType.HOST_TOOL_CALL,
        payload={
            "callId": call_id,
            "name": name,
            "arguments": redact_sensitive(arguments),
            "sideEffect": side_effect,
            "requiresConfirmation": requires_confirmation,
        },
        conversation_id=conversation_id,
        request_id=request_id,
    )


def confirmation_required(
    *,
    conversation_id: int | None = None,
    request_id: str | None,
    call_id: str | None,
    name: str,
    tool_type: str | None,
    side_effect: str | None,
    arguments: Any,
    expires_at: str | None,
) -> RunEvent:
    """需要用户确认的工具调用事件；客户端用 ``callId`` 回传裁决。"""

    return RunEvent(
        type=RunEventType.CONFIRMATION_REQUIRED,
        payload={
            "callId": call_id,
            "name": name,
            "toolType": tool_type,
            "sideEffect": side_effect,
            "summary": {"arguments": redact_sensitive(arguments)},
            "expiresAt": expires_at,
        },
        conversation_id=conversation_id,
        request_id=request_id,
    )


def question_required(
    *,
    conversation_id: int | None = None,
    request_id: str | None,
    question_id: str | None,
    question: str,
    description: str | None,
    options: list,
    allow_free_text: bool,
    require_selection: bool,
    expires_at: str | None,
) -> RunEvent:
    """需要用户回答的问题事件（``ask_user`` 工具的等待态）。"""

    return RunEvent(
        type=RunEventType.QUESTION_REQUIRED,
        payload={
            "questionId": question_id,
            "question": question,
            "description": description,
            "options": options,
            "allowFreeText": allow_free_text,
            "requireSelection": require_selection,
            "expiresAt": expires_at,
        },
        conversation_id=conversation_id,
        request_id=request_id,
    )


def session_ready(*, payload: dict) -> RunEvent:
    """握手完成事件；payload 由网关按当前连接状态组装。"""

    return RunEvent(type=RunEventType.SESSION_READY, payload=payload)


def pong(*, request_id: str | None = None) -> RunEvent:
    """ping 的应答事件。"""

    return RunEvent(type=RunEventType.PONG, payload={}, request_id=request_id)


class LoopEventBuilder:
    """按一次请求绑定 conversation/loop/request_id 的事件构造器。

    业务侧在 loop 创建后实例化，后续 agent_step_* / agent_loop_* /
    message_* 事件都通过方法构造，调用点无需重复传上下文参数。
    ``message_started`` 在 loop 创建前发出，单独使用模块级构造函数。
    """

    def __init__(self, conversation, loop, *, request_id: str):
        self.conversation = conversation
        self.loop = loop
        self.request_id = request_id

    def message_delta(self, content: str) -> RunEvent:
        return message_delta(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            content=content,
        )

    def citation(self, value: dict) -> RunEvent:
        return citation(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            citation=value,
        )

    def loop_started(self) -> RunEvent:
        return agent_loop_started(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
        )

    def loop_completed(self) -> RunEvent:
        return agent_loop_completed(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
        )

    def step_started(self, step, **payload_kwargs) -> RunEvent:
        return agent_step_started(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
            step=step,
            **payload_kwargs,
        )

    def step_completed(self, step, **payload_kwargs) -> RunEvent:
        return agent_step_completed(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
            step=step,
            **payload_kwargs,
        )

    def step_delta(self, step, *, field: str, content: str) -> RunEvent:
        return agent_step_delta(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
            step=step,
            field=field,
            content=content,
        )

    def message_completed(
        self,
        *,
        result,
        content: str,
        content_blocks: list,
        loop_run_id=None,
    ) -> RunEvent:
        return message_completed(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            result=result,
            content=content,
            content_blocks=content_blocks,
            loop_run_id=loop_run_id,
        )

    def error(self, payload: dict) -> RunEvent:
        return error(
            request_id=self.request_id,
            payload=payload,
            conversation_id=self.conversation.id,
        )


# ---------------------------------------------------------------------------
# 服务层流式 item -> RunEvent（REST SSE 出口）
# ---------------------------------------------------------------------------

_STEP_EVENT_TYPES = {
    RunEventType.AGENT_LOOP_STARTED,
    RunEventType.AGENT_LOOP_COMPLETED,
    RunEventType.AGENT_STEP_STARTED,
    RunEventType.AGENT_STEP_DELTA,
    RunEventType.AGENT_STEP_COMPLETED,
}


def _tool_event_context(item: dict[str, Any]) -> tuple[str, str | None, Any]:
    """从服务层工具事件里取出（工具名、工具类型、入参）。

    ``tool_started`` / ``tool_completed`` 把工具信息放在顶层；``tool_call``
    与 ``tool_result`` 走 payload；两种来源都兼容，缺失时返回空值而不是抛错，
    以免单个字段缺省把整条 SSE 流打挂。
    """

    payload = item.get("payload") or {}
    name = item.get("tool") or payload.get("tool") or payload.get("name") or ""
    tool_type = item.get("tool_type") or payload.get("toolType")
    arguments = item.get("arguments")
    if arguments is None:
        arguments = payload.get("arguments")
    return str(name), tool_type, arguments


def run_events_from_stream_item(
    item: dict[str, Any], *, request_id: str | None = None
) -> list[RunEvent]:
    """把 conversation 服务层的流式 item 映射为线协议 RunEvent。

    SSE 出口用它把内部事件一次性翻译成线协议事件；``completed`` 是服务层
    内部终态，展开为若干 ``citation`` 加一条 ``message_completed``；无法识别
    的内部 item 返回空列表（不产生线上事件）。
    """

    event_type = str(item.get("type", ""))
    conversation = item.get("conversation")
    conversation_id = getattr(conversation, "id", None)
    event_request_id = request_id or item.get("request_id")

    if event_type == RunEventType.MESSAGE_DELTA:
        return [
            message_delta(
                conversation_id=conversation_id,
                request_id=event_request_id,
                content=str(item.get("content", "")),
            )
        ]

    if event_type in _STEP_EVENT_TYPES:
        # agent_step_* / agent_loop_* 的 payload 已由 build_step_payload 组装，
        # 这里只补齐信封字段；没有调用方时 requestId 留空。
        return [
            RunEvent(
                type=event_type,
                payload=dict(item.get("payload") or {}),
                conversation_id=conversation_id,
                request_id=event_request_id,
            )
        ]

    if event_type == RunEventType.TOOL_CALL:
        payload = item.get("payload") or {}
        return [
            tool_call(
                conversation_id=conversation_id,
                request_id=event_request_id,
                name=str(payload.get("tool") or payload.get("name") or ""),
                tool_input=payload.get("input"),
                call_id=payload.get("toolCallId") or payload.get("callId"),
            )
        ]

    if event_type in {RunEventType.TOOL_RESULT, RunEventType.CONFIRMATION_REQUIRED}:
        payload = item.get("payload") or {}
        name, tool_type, arguments = _tool_event_context(item)
        if event_type == RunEventType.TOOL_RESULT:
            return [
                tool_result(
                    conversation_id=conversation_id,
                    request_id=event_request_id,
                    name=name,
                    result=payload.get("result"),
                    status=payload.get("status"),
                    error_payload=payload.get("error"),
                )
            ]
        metadata = payload.get("metadata") or {}
        return [
            confirmation_required(
                conversation_id=conversation_id,
                request_id=event_request_id,
                call_id=payload.get("call_id") or item.get("tool_call_id"),
                name=name,
                tool_type=tool_type,
                side_effect=metadata.get("side_effect"),
                arguments=arguments,
                expires_at=metadata.get("expires_at"),
            )
        ]

    if event_type == RunEventType.ERROR:
        return [
            error(
                request_id=event_request_id,
                payload=dict(item.get("payload") or {}),
                conversation_id=conversation_id,
            )
        ]

    if event_type == "completed":
        assistant = item.get("assistant")
        result = item.get("result")
        if result is None:
            return []
        events = [
            citation(
                conversation_id=conversation_id,
                request_id=event_request_id,
                citation=value,
            )
            for value in (result.citations or [])
        ]
        events.append(
            message_completed(
                conversation_id=conversation_id,
                request_id=event_request_id or "",
                result=result,
                content=result.content,
                content_blocks=getattr(assistant, "content_blocks", None) or [],
                loop_run_id=result.loop_id,
            )
        )
        return events

    return []


# ---------------------------------------------------------------------------
# 步骤 payload（agent_step_* 事件与 loop step 共享的字段口径）
# ---------------------------------------------------------------------------


def build_step_payload(
    step,
    *,
    loop_run_id,
    sequence: int | None = None,
    citation_refs: list | None = None,
    with_input: bool = False,
    with_output: bool = False,
    with_tool: bool = False,
    with_skill: bool = False,
    with_thinking: bool = False,
) -> dict[str, Any]:
    """构造 agent_step_* 事件的 payload，统一协议字段命名。

    ``with_thinking`` 控制 thinkingText 是否总是输出：网关路径默认仅在
    存在思考文本时携带该字段；REST 流式路径保持 always-present 语义。
    """

    payload = {
        "loopRunId": str(loop_run_id),
        "stepId": str(step.id),
        "sequence": step.sequence if sequence is None else sequence,
        "stepType": step.step_type,
        "title": step.title,
        "status": step.status,
    }
    if with_input:
        payload["inputSummary"] = step.input_summary
    if with_output:
        payload["outputSummary"] = step.output_summary
    thinking = getattr(step, "thinking_text", None)
    if with_thinking or thinking:
        payload["thinkingText"] = thinking
    if with_tool:
        payload["toolName"] = step.tool_name
    if with_skill:
        payload["skillName"] = step.skill_name
        payload["skillVersion"] = step.skill_version
    if citation_refs is not None:
        payload["citationRefs"] = citation_refs
    return payload
