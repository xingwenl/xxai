"""可复用的 Agent 运行时内部模块。

该模块只定义 Agent 执行所需的稳定内部契约，不直接暴露 REST 或 WebSocket
协议。外部协议通过 conversation/gateway 适配器接入，避免协议细节渗透到
模型循环和工具执行逻辑。
"""

from app.modules.agent_runtime.contracts import (
    AgentEvent,
    AgentRequest,
    AgentResult,
    ToolRoundState,
    ToolCall,
    ToolOutcome,
)
from app.modules.agent_runtime.hooks import AgentRuntimeHooks
from app.modules.agent_runtime.runtime import AgentRuntime
from app.modules.agent_runtime.context import AgentRuntimeContext
from app.modules.agent_runtime.event_adapters import event_from_legacy, event_to_legacy
from app.modules.agent_runtime.tools import CallbackToolExecutor, ToolCatalog
from app.modules.agent_runtime.persistence import (
    AgentRunPersistence,
    BufferedAgentRunPersistence,
    NullAgentRunPersistence,
)
from app.modules.agent_runtime.lifecycle import (
    AgentRunLifecycle,
    RunStatus,
    generation_step_status_for,
    loop_status_for,
    loop_summary_for,
    resolve_result_run_status,
)
from app.modules.agent_runtime.tool_events import (
    build_tool_event,
    build_tool_completed_event,
    classify_tool_type,
    summarize_tool_value,
    tool_result_content,
    normalize_tool_step_status,
)
from app.modules.agent_runtime.errors import (
    AgentRuntimeError,
    cancellation_error,
    error_from_exception,
)
from app.modules.agent_runtime.legacy_adapter import LegacyGraphEventAdapter
from app.modules.agent_runtime.model_stream import ModelStreamAdapter
from app.modules.agent_runtime.graph_bridge import LegacyGraphRuntimeBridge
from app.modules.agent_runtime.tool_loop import ToolRoundExecutor
from app.modules.agent_runtime.langchain_adapter import build_langchain_messages
from app.modules.agent_runtime.adapters import (
    agent_result_from_legacy,
    invoke_legacy_tool,
    tool_outcome_from_legacy,
    tool_call_from_legacy,
)

__all__ = [
    "AgentEvent",
    "AgentRequest",
    "AgentResult",
    "ToolRoundState",
    "ToolCall",
    "ToolOutcome",
    "AgentRuntimeHooks",
    "AgentRuntime",
    "AgentRuntimeContext",
    "event_from_legacy",
    "event_to_legacy",
    "ToolCatalog",
    "CallbackToolExecutor",
    "AgentRunPersistence",
    "NullAgentRunPersistence",
    "BufferedAgentRunPersistence",
    "AgentRunLifecycle",
    "RunStatus",
    "resolve_result_run_status",
    "generation_step_status_for",
    "loop_status_for",
    "loop_summary_for",
    "build_tool_event",
    "build_tool_completed_event",
    "classify_tool_type",
    "summarize_tool_value",
    "AgentRuntimeError",
    "cancellation_error",
    "LegacyGraphEventAdapter",
    "ModelStreamAdapter",
    "LegacyGraphRuntimeBridge",
    "ToolRoundExecutor",
    "build_langchain_messages",
    "error_from_exception",
    "tool_result_content",
    "normalize_tool_step_status",
    "invoke_legacy_tool",
    "agent_result_from_legacy",
    "tool_outcome_from_legacy",
    "tool_call_from_legacy",
]
