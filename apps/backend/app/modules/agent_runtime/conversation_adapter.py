"""AgentRuntime 到 conversation 流式内部事件的窄适配层。

这里不负责数据库写入，也不负责公开 SSE 序列化。它只把 runtime 的供应商无关
事件转换成 conversation 已经认识的事件形状，避免 runtime 依赖 conversation。
"""

from collections.abc import AsyncIterator
from typing import Any

from app.modules.agent_runtime.contracts import AgentEvent, AgentEventType
from app.modules.agent_runtime.event_adapters import event_to_legacy
from app.modules.agent_runtime.tool_events import summarize_tool_value


async def stream_runtime_as_conversation(
    runtime_stream: AsyncIterator[AgentEvent],
) -> AsyncIterator[dict[str, Any]]:
    """将 runtime 事件转换为旧 conversation 流事件。

    一个模型轮次的 TOOL_STARTED 可能包含多个调用，因此适配器展开为多个
    `tool_started`，让 REST SSE 与旧 Graph 路径保持相同的逐工具生命周期。
    """

    async for event in runtime_stream:
        if event.type == AgentEventType.TOOL_STARTED:
            payload = event.payload
            for call in payload.get("tool_calls", []):
                arguments = call.get("arguments")
                # loop_step.input_summary 是数据库文本字段；runtime 内部
                # 保留结构化参数，跨过 conversation 持久化边界时统一序列化。
                # 与 legacy _build_tool_event 使用同一紧凑序列化与 300 字上限，
                # 避免灰度/legacy 两个入口写出不同 input_summary。
                arguments = summarize_tool_value(arguments or {}, limit=300)
                yield {
                    "type": "tool_started",
                    "tool_call_id": call["id"],
                    "tool": call["name"],
                    # AgentLoop 已尽量补齐工具分类；描述缺失时仍按 host_tool
                    # 回退，兼容旧版工具对象或直接构造的测试事件。
                    "tool_type": call.get("tool_type") or "host_tool",
                    "input_summary": arguments,
                }
            continue
        if event.type == AgentEventType.TOOL_COMPLETED:
            payload = event.payload
            outcome = payload.get("outcome")
            if outcome is not None:
                outcome_data = outcome
            else:
                outcome_data = {
                    "status": payload.get("status", "completed"),
                    "result": payload.get("result"),
                    "error": payload.get("error"),
                    "call_id": payload.get("tool_call_id"),
                }
            yield {
                "type": "tool_completed",
                "tool_call_id": payload.get("tool_call_id"),
                "tool": payload.get("tool_name", ""),
                # 透出结构化参数与分类：等待态等提前收尾场景由协议层自行
                # 构造最终 GraphResult/快照，需要与 tool_started 同源信息。
                "tool_type": payload.get("tool_type"),
                "arguments": payload.get("arguments"),
                "outcome": outcome_data,
                # 等待态的消息快照（活的 adapter 层对象）随事件交给 conversation
                # 服务层落检查点；它不参与 SSE/WS 出站序列化。
                "pending_context": getattr(outcome_data, "pending_context", None),
            }
            continue
        yield event_to_legacy(event)
