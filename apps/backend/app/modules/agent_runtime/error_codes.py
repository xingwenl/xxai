"""协议与运行时的稳定错误码登记表。

对外出现的字符串错误码（WS/SSE ``error`` 事件的 ``payload.code``、REST 的
``error_code``）统一在这里登记。此前这些码散落在网关、运行时、工具的十几处
字面量里，调用方无法确认「线上到底可能出现哪些码」，新增时也容易撞出近义码。

**不在这里登记 code→retryable 映射**：同一个码在不同阶段的语义并不相同
（``request_in_progress`` 是「稍后重发」、``context_length_exceeded`` 是
「换一轮新对话都不一定有用」），重试判断属于调用方，由各出口在构造错误时
显式给出 ``retryable``。本表只回答「有哪些码」。
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """会出现在协议错误事件与 REST ``error_code`` 里的稳定错误码。"""

    # 握手与连接
    EMBED_TOKEN = "embed_token"
    UNSUPPORTED_PROTOCOL_VERSION = "unsupported_protocol_version"
    UNSUPPORTED_SDK_VERSION = "unsupported_sdk_version"

    # 入站消息校验与并发
    REQUEST_ID_REQUIRED = "request_id_required"
    REQUEST_IN_PROGRESS = "request_in_progress"
    INVALID_CONVERSATION_ID = "invalid_conversation_id"
    INVALID_ATTACHMENTS = "invalid_attachments"
    TEXT_REQUIRED = "text_required"
    INVALID_THINKING = "invalid_thinking"
    INVALID_HOST_TOOLS = "invalid_host_tools"

    # 模型与运行时
    CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
    AGENT_UPSTREAM_UNAVAILABLE = "agent_upstream_unavailable"
    AGENT_REQUEST_FAILED = "agent_request_failed"
    AGENT_REQUEST_CANCELLED = "agent_request_cancelled"
    CHAT_MODEL_UNAVAILABLE = "chat_model_unavailable"

    # 工具
    TOOL_NOT_AVAILABLE = "tool_not_available"
    INVALID_ARGUMENTS = "invalid_arguments"
    HOST_TOOL_FAILED = "host_tool_failed"
    HOST_TOOL_EXECUTION_FAILED = "host_tool_execution_failed"
    HOST_TOOL_EXPIRED = "host_tool_expired"
    HOST_TOOL_EXECUTION_TIMEOUT = "host_tool_execution_timeout"

    # 挂起运行的确认与续跑
    RUN_CONFIRMATION_NOT_FOUND = "run_confirmation_not_found"
    RUN_CONFIRMATION_ALREADY_RESOLVED = "run_confirmation_already_resolved"
    RUN_CONFIRMATION_EXPIRED = "run_confirmation_expired"
    RUN_RESUME_UNAVAILABLE = "run_resume_unavailable"

    # 网关与配额
    REQUEST_FAILED = "request_failed"
    QUOTA_EXCEEDED = "quota_exceeded"
    QUOTA_UNAVAILABLE = "quota_unavailable"
