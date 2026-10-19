"""Agent runtime 的通用错误语义。"""

import asyncio
import re
from dataclasses import dataclass
from app.modules.agent_runtime.error_codes import ErrorCode
from typing import Any


@dataclass(slots=True, frozen=True)
class AgentRuntimeError:
    """不携带供应商内部细节的运行时错误。"""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        """转换为协议层可继续封装的普通字典。"""

        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details or {},
        }


def cancellation_error() -> AgentRuntimeError:
    """统一取消错误，取消不应被误报成供应商故障。"""

    return AgentRuntimeError(
        code=ErrorCode.AGENT_REQUEST_CANCELLED,
        message="Agent 请求已取消",
        retryable=True,
    )


def error_from_exception(error: BaseException) -> AgentRuntimeError:
    """将常见运行时异常转换为不泄露内部细节的错误。

    分类语义与 legacy conversation 错误适配保持一致：上下文超限不可重试、
    HTTP 5xx/连接失败可重试、客户端 4xx 不重试。错误详情只暴露状态码与
    异常类型，不把供应商返回的原始文本（可能含密钥或堆栈）透传给协议层。
    """

    if isinstance(error, (asyncio.CancelledError, GeneratorExit)):
        return cancellation_error()
    raw = str(error) or type(error).__name__
    lowered = raw.lower()
    if _is_context_length_exceeded(lowered):
        return AgentRuntimeError(
            code=ErrorCode.CONTEXT_LENGTH_EXCEEDED,
            message=(
                "对话或本次查询结果超过模型上下文上限，"
                "请缩小查询范围或开启新对话"
            ),
            retryable=False,
            details={"statusCode": "", "exceptionType": type(error).__name__},
        )
    status_code = _extract_status_code(error, raw)
    is_connection_error = isinstance(
        error, (TimeoutError, ConnectionError)
    ) or any(
        marker in lowered
        for marker in (
            "connection",
            "connect",
            "timeout",
            "bad gateway",
            "upstream",
        )
    )
    if status_code is not None and status_code >= 500:
        return AgentRuntimeError(
            code=ErrorCode.AGENT_UPSTREAM_UNAVAILABLE,
            message=f"Agent 连接失败（HTTP {status_code}），本轮对话已结束",
            retryable=True,
            details={
                "statusCode": str(status_code),
                "exceptionType": type(error).__name__,
            },
        )
    if is_connection_error:
        return AgentRuntimeError(
            code=ErrorCode.AGENT_UPSTREAM_UNAVAILABLE,
            message="Agent 连接失败，本轮对话已结束",
            retryable=True,
            details={
                "statusCode": str(status_code) if status_code else "",
                "exceptionType": type(error).__name__,
            },
        )
    return AgentRuntimeError(
        code=ErrorCode.AGENT_REQUEST_FAILED,
        message="Agent 请求失败，本轮对话已结束",
        retryable=False,
        details={
            "statusCode": str(status_code) if status_code else "",
            "exceptionType": type(error).__name__,
        },
    )


def _is_context_length_exceeded(lowered_message: str) -> bool:
    """识别 OpenAI/DeepSeek 兼容的上下文超限错误文本标记。"""

    return any(
        marker in lowered_message
        for marker in (
            "context_length_exceeded",
            "maximum context length",
            "maximum context",
            "prompt is too long",
        )
    )


def _extract_status_code(error: BaseException, raw_message: str) -> int | None:
    """从异常属性或消息文本提取 HTTP 状态码，保持供应商无关。"""

    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    match = re.search(r"\b([45]\d{2})\b", raw_message)
    return int(match.group(1)) if match else None
