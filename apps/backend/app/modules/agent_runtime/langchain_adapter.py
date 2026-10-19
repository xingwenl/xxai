"""LangChain 模型与 agent_runtime 契约之间的适配。"""

import json
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)

from app.modules.agent_runtime.contracts import AgentEvent, AgentEventType, ToolCall, ToolOutcome
from app.modules.agent_runtime.loop import ModelTurn
from app.modules.agent_runtime.message_text import (
    extract_text_content,
    extract_thinking_text,
)
from app.modules.agent_runtime.tool_events import classify_tool_type


def _normalize_usage(usage: Any) -> dict[str, int] | None:
    """统一不同 LangChain/provider 的 token 字段名。"""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    total = usage.get("total_tokens")
    if total is None and isinstance(prompt, int) and isinstance(completion, int):
        total = prompt + completion
    if not all(isinstance(value, int) and value >= 0 for value in (prompt, completion, total)):
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def build_langchain_messages(
    *,
    system_prompt: str,
    user_message: str,
    history: list[Any] | None = None,
    image_parts: list[dict[str, Any]] | None = None,
    document_text_parts: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """组装 runtime 可直接消费的 LangChain system/history/user 消息。"""

    user_content: Any = user_message
    extra_parts = [*(document_text_parts or []), *(image_parts or [])]
    if extra_parts:
        user_content = [{"type": "text", "text": user_message}, *extra_parts]
    return [
        SystemMessage(content=system_prompt),
        *(history or []),
        HumanMessage(content=user_content),
    ]


def model_turn_from_message(
    message: AIMessage, tools: list[Any] | None = None
) -> ModelTurn:
    """将 LangChain AIMessage 的工具调用归一化为 ToolCall。

    ``tools`` 用于在模型第一次返回工具调用时就补齐 ``tool_type``（builtin/
    mcp/skill/host），让 loop 的工具事件无需理解协议层工具对象即可携带
    稳定分类；找不到对应工具时保留 None，由事件消费方按 host_tool 回退。
    """

    tool_by_name = {
        getattr(tool, "name", None): tool for tool in (tools or []) if tool is not None
    }
    calls = []
    for index, call in enumerate(getattr(message, "tool_calls", []) or []):
        name = str(call.get("name", ""))
        tool = tool_by_name.get(name)
        calls.append(
            ToolCall(
                id=str(call.get("id") or f"tool-call-{index}"),
                name=name,
                arguments=(
                    call.get("args") if isinstance(call.get("args"), dict) else {}
                ),
                tool_type=classify_tool_type(tool) if tool is not None else None,
            )
        )
    content = extract_text_content(message.content)
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict):
        response_metadata = getattr(message, "response_metadata", None) or {}
        usage = response_metadata.get("token_usage") or response_metadata.get("usage")
    normalized_usage = _normalize_usage(usage)
    return ModelTurn(
        content=content,
        tool_calls=calls,
        metadata={"usage": normalized_usage} if normalized_usage else {},
    )


def tool_message_from_outcome(call: ToolCall, outcome: ToolOutcome) -> ToolMessage:
    """把统一工具结果转换成下一轮模型可理解的 ToolMessage。"""

    value: Any = outcome.result
    if outcome.error is not None:
        value = {"error": outcome.error, "status": str(outcome.status)}
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return ToolMessage(content=value, tool_call_id=call.id)


def messages_for_model(messages: list[Any]) -> list[Any]:
    """将 runtime 内部消息转换为 LangChain 消息，过滤 UI-only 对象。"""

    converted = []
    for item in messages:
        if isinstance(item, (AIMessage, HumanMessage, SystemMessage, ToolMessage)):
            converted.append(item)
        elif isinstance(item, ModelTurn):
            converted.append(
                AIMessage(
                    content=item.content,
                    tool_calls=[
                        {
                            "id": call.id,
                            "name": call.name,
                            "args": call.arguments,
                        }
                        for call in item.tool_calls
                    ],
                )
            )
        elif isinstance(item, ToolOutcome):
            call_id = item.call_id or item.metadata.get("call_id") or "unknown"
            converted.append(
                tool_message_from_outcome(
                    ToolCall(call_id, "tool"), item
                )
            )
        elif isinstance(item, str):
            converted.append(HumanMessage(content=item))
    return converted


# 运行检查点里保存的上下文快照的存储格式。它必须与 messages_for_model 认识的
# 对象种类一一对应，否则续跑时模型看到的上下文会与挂起那一刻不同。
_CONTEXT_MESSAGE_KINDS = (AIMessage, HumanMessage, SystemMessage, ToolMessage)


# 轮次元数据里不能进快照的键：``pending_context`` 就是快照本身，
# 它只为了把「挂起那刻的上下文」带回上层（见 AgentLoop 的等待态短路），
# 值是活对象列表，序列化时必须剔除，否则会自嵌套且无法落库。
_DUMP_SKIPPED_METADATA_KEYS = frozenset({"pending_context"})


def _json_safe(value: Any) -> Any:
    """把任意元数据折成可入库的 JSON 结构。

    工具结果的 metadata 由各工具自行填充，不保证只有标量；这里统一兜一层，
    让检查点写入不会因为某个工具的私有元数据而整轮请求失败（无法识别的
    值退化成字符串，续跑只需要它可读，不需要它可还原）。
    """

    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def dump_context(messages: list[Any]) -> list[dict[str, Any]]:
    """把等待确认那一刻的消息快照序列化成可入库的 JSON 结构。

    只处理 :func:`messages_for_model` 认识的对象种类；未知类型直接跳过，
    与模型调用时的丢弃语义保持一致。序列化格式属于 adapter 层，调用方
    （运行检查点）只负责存与取，不解释内容。
    """

    dumped: list[dict[str, Any]] = []
    for item in messages:
        if isinstance(item, _CONTEXT_MESSAGE_KINDS):
            dumped.append({"kind": "message", "data": messages_to_dict([item])[0]})
        elif isinstance(item, ModelTurn):
            metadata = {
                key: value
                for key, value in (item.metadata or {}).items()
                if key not in _DUMP_SKIPPED_METADATA_KEYS
            }
            dumped.append(
                {
                    "kind": "model_turn",
                    "content": item.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "tool_type": call.tool_type,
                        }
                        for call in item.tool_calls
                    ],
                    "metadata": _json_safe(metadata),
                }
            )
        elif isinstance(item, ToolOutcome):
            dumped.append(
                {
                    "kind": "tool_outcome",
                    "status": str(item.status),
                    "result": _json_safe(item.result),
                    "error": _json_safe(item.error),
                    "call_id": item.call_id,
                    "audit_id": item.audit_id,
                    "confirmation_id": item.confirmation_id,
                    "metadata": _json_safe(item.metadata),
                }
            )
        elif isinstance(item, str):
            dumped.append({"kind": "text", "data": item})
    return dumped


def load_context(payload: list[dict[str, Any]] | None) -> list[Any]:
    """把 :func:`dump_context` 的产物还原成可用于续跑的消息列表。"""

    restored: list[Any] = []
    for entry in payload or []:
        kind = entry.get("kind")
        if kind == "message":
            restored.extend(messages_from_dict([entry["data"]]))
        elif kind == "model_turn":
            restored.append(
                ModelTurn(
                    content=entry.get("content", ""),
                    tool_calls=[
                        ToolCall(
                            id=str(call.get("id") or ""),
                            name=str(call.get("name") or ""),
                            arguments=dict(call.get("arguments") or {}),
                            tool_type=call.get("tool_type"),
                        )
                        for call in entry.get("tool_calls") or []
                    ],
                    metadata=dict(entry.get("metadata") or {}),
                )
            )
        elif kind == "tool_outcome":
            restored.append(
                ToolOutcome(
                    status=entry.get("status", "completed"),
                    result=entry.get("result"),
                    error=entry.get("error"),
                    call_id=entry.get("call_id"),
                    audit_id=entry.get("audit_id"),
                    confirmation_id=entry.get("confirmation_id"),
                    metadata=dict(entry.get("metadata") or {}),
                )
            )
        elif kind == "text":
            restored.append(entry.get("data", ""))
    return restored


class LangChainModelInvoker:
    """将 LangChain ``ainvoke`` 模型适配为 AgentLoop 的模型调用器。"""

    def __init__(
        self,
        model: Any,
        tools: list[Any] | None = None,
        *,
        streaming: bool = False,
    ) -> None:
        self._model = model
        self._tools = tools or []
        self._streaming = streaming
        self._bound_model = self._bind_tools(model)

    def _bind_tools(self, model: Any) -> Any:
        if not self._tools or not hasattr(model, "bind_tools"):
            return model
        return model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema or {"type": "object"},
                    },
                }
                for tool in self._tools
            ]
        )

    async def __call__(self, messages: list[Any], *, emit, allow_tools: bool = True) -> ModelTurn:
        # 收尾轮必须使用未绑定工具的原始模型；仅靠调用方忽略 tool_calls
        # 不够，因为供应商仍可能执行或生成工具调用。
        model = self._bound_model if allow_tools else self._model
        if self._streaming and hasattr(model, "astream"):
            response = None
            thinking_parts: list[str] = []
            async for chunk in model.astream(messages_for_model(messages)):
                if response is None:
                    response = chunk
                else:
                    try:
                        response = response + chunk
                    except TypeError:
                        pass
                thinking = extract_thinking_text(chunk)
                if thinking:
                    thinking_parts.append(thinking)
                    await emit(
                        AgentEvent(
                            AgentEventType.THINKING_DELTA,
                            {"content": thinking},
                        )
                    )
                content = extract_text_content(chunk.content)
                if content:
                    await emit(
                        AgentEvent(
                            AgentEventType.MESSAGE_DELTA,
                            {"content": content},
                        )
                    )
            if response is None:
                response = AIMessage(content="")
            if not isinstance(response, AIMessage):
                response = AIMessage(content=getattr(response, "content", str(response)))
            turn = model_turn_from_message(response, tools=self._tools)
            if thinking_parts:
                turn.metadata["thinking_text"] = "".join(thinking_parts)
            return turn
        response = await model.ainvoke(messages_for_model(messages))
        if not isinstance(response, AIMessage):
            response = AIMessage(content=getattr(response, "content", str(response)))
        turn = model_turn_from_message(response, tools=self._tools)
        thinking = extract_thinking_text(response)
        if thinking:
            turn.metadata["thinking_text"] = thinking
        return turn
