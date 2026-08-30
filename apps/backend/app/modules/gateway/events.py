"""ai-agent.v1 协议事件中枢。

Embed 网关的协议事件集中在本文件，按事件类型组织为两类：

- 出站构造（build_*）：业务侧（gateway.runtime）直接产出协议形状的完整事件
  ``{type, conversation_id, request_id, payload}``，主循环不再二次转换。
- 内部事件转换（INBOUND_PAYLOAD_HANDLERS）：dispatcher 等内部来源的事件
  不带 payload 字段，由主循环按类型转换为协议 payload。

新增协议事件时，只需在本文件注册对应的构造/转换函数。
"""

from collections.abc import Callable

from app.modules.conversation.runtime import build_step_payload
from app.modules.host_tool.services import redact_sensitive


# ---------------------------------------------------------------------------
# 出站事件构造：业务侧直接产出协议形状事件
# ---------------------------------------------------------------------------


def build_message_started(*, conversation_id: int | None, request_id: str) -> dict:
    """请求已被接受的通知事件，payload 为空对象。"""
    return {
        "type": "message_started",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": {},
    }


def build_message_delta(
    *, conversation_id: int | None, request_id: str, content: str
) -> dict:
    """模型增量正文。"""
    return {
        "type": "message_delta",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": {"content": content},
    }


def build_citation(
    *, conversation_id: int | None, request_id: str, citation: dict
) -> dict:
    """知识库引用，payload 直接透传 citation。"""
    return {
        "type": "citation",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": citation,
    }


def _loop_payload(loop) -> dict:
    """agent_loop_* 事件共用的 payload 结构。"""
    return {
        "loopRunId": str(loop.id),
        "status": loop.status,
        "summary": loop.summary,
    }


def build_agent_loop_started(
    *, conversation_id: int | None, request_id: str, loop
) -> dict:
    return {
        "type": "agent_loop_started",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": _loop_payload(loop),
    }


def build_agent_loop_completed(
    *, conversation_id: int | None, request_id: str, loop
) -> dict:
    return {
        "type": "agent_loop_completed",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": _loop_payload(loop),
    }


def build_agent_step_started(
    *,
    conversation_id: int | None,
    request_id: str,
    loop,
    step,
    **payload_kwargs,
) -> dict:
    """agent_step_started 事件，payload 由 build_step_payload 构造。"""
    return {
        "type": "agent_step_started",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": build_step_payload(step, loop_run_id=loop.id, **payload_kwargs),
    }


def build_agent_step_completed(
    *,
    conversation_id: int | None,
    request_id: str,
    loop,
    step,
    **payload_kwargs,
) -> dict:
    """agent_step_completed 事件，payload 由 build_step_payload 构造。"""
    return {
        "type": "agent_step_completed",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": build_step_payload(step, loop_run_id=loop.id, **payload_kwargs),
    }


def build_agent_step_delta(
    *,
    conversation_id: int | None,
    request_id: str,
    loop,
    step,
    field: str,
    content: str,
) -> dict:
    """模型生成过程中的增量事件（如 thinking 流）。"""
    return {
        "type": "agent_step_delta",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": {
            "loopRunId": str(loop.id),
            "stepId": str(step.id),
            "sequence": step.sequence,
            "stepType": step.step_type,
            "field": field,
            "content": content,
        },
    }


def build_message_completed(
    *,
    conversation_id: int | None,
    request_id: str,
    result,
    content: str,
    content_blocks: list,
    loop_run_id=None,
) -> dict:
    """最终回答事件，payload 组装最终状态、用量与 loop 摘要。"""
    return {
        "type": "message_completed",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": {
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
    }


def build_error(
    *,
    request_id: str,
    payload: dict,
    conversation_id: int | None = None,
) -> dict:
    """错误事件，payload 为稳定的可展示错误结构。"""
    return {
        "type": "error",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "payload": payload,
    }


class LoopEventBuilder:
    """按一次请求绑定 conversation/loop/request_id 的事件构造器。

    业务侧在 loop 创建后实例化，后续 agent_step_* / agent_loop_* /
    message_* 事件都通过方法构造，调用点无需重复传上下文参数。
    ``message_started`` 在 loop 创建前发出，单独使用 build_message_started。
    """

    def __init__(self, conversation, loop, *, request_id: str):
        self.conversation = conversation
        self.loop = loop
        self.request_id = request_id

    def message_delta(self, content: str) -> dict:
        return build_message_delta(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            content=content,
        )

    def citation(self, citation: dict) -> dict:
        return build_citation(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            citation=citation,
        )

    def loop_started(self) -> dict:
        return build_agent_loop_started(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
        )

    def loop_completed(self) -> dict:
        return build_agent_loop_completed(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
        )

    def step_started(self, step, **payload_kwargs) -> dict:
        return build_agent_step_started(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
            step=step,
            **payload_kwargs,
        )

    def step_completed(self, step, **payload_kwargs) -> dict:
        return build_agent_step_completed(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            loop=self.loop,
            step=step,
            **payload_kwargs,
        )

    def step_delta(self, step, *, field: str, content: str) -> dict:
        return build_agent_step_delta(
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
    ) -> dict:
        return build_message_completed(
            conversation_id=self.conversation.id,
            request_id=self.request_id,
            result=result,
            content=content,
            content_blocks=content_blocks,
            loop_run_id=loop_run_id,
        )

    def error(self, payload: dict) -> dict:
        return build_error(
            request_id=self.request_id,
            payload=payload,
            conversation_id=self.conversation.id,
        )


# ---------------------------------------------------------------------------
# 内部事件转换：dispatcher 等来源的事件 -> 协议 payload
# ---------------------------------------------------------------------------


def _payload_host_tool_call(event: dict) -> dict:
    return {
        "callId": event["call_id"],
        "name": event["name"],
        "arguments": redact_sensitive(event["arguments"]),
        "sideEffect": event["side_effect"],
        "requiresConfirmation": event["requires_confirmation"],
    }


def _payload_confirmation_required(event: dict) -> dict:
    return {
        "callId": event["call_id"],
        "name": event["name"],
        "toolType": event["tool_type"],
        "sideEffect": event["side_effect"],
        "summary": {"arguments": redact_sensitive(event["arguments"])},
        "expiresAt": event.get("expires_at"),
    }


def _payload_question_required(event: dict) -> dict:
    return {
        "questionId": event["question_id"],
        "question": event["question"],
        "description": event.get("description"),
        "options": event["options"],
        "allowFreeText": event["allow_free_text"],
        "requireSelection": event["require_selection"],
        "expiresAt": event.get("expires_at"),
    }


# dispatcher 等内部来源的事件类型 -> 协议 payload 构造器
INBOUND_PAYLOAD_HANDLERS: dict[str, Callable[[dict], dict]] = {
    "host_tool_call": _payload_host_tool_call,
    "confirmation_required": _payload_confirmation_required,
    "question_required": _payload_question_required,
}


def event_to_protocol_payload(event_type: str, event: dict) -> dict:
    """把不带 payload 的内部事件转换为协议 payload；未知类型返回空对象。"""
    handler = INBOUND_PAYLOAD_HANDLERS.get(event_type)
    return handler(event) if handler is not None else {}
