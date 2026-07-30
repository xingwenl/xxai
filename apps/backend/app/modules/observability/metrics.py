"""Prometheus 指标定义。

指标只使用低基数标签；请求和主体关联信息由调用方写入结构化日志，
避免把 requestId、最终用户或敏感业务参数扩散到时序数据库。
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

METRIC_LABELS = ("result", "resource", "code")

AUTHENTICATION_TOTAL = Counter(
    "agent_gateway_authentication_total",
    "WebSocket authentication results",
    ("result",),
)
CONNECTIONS_TOTAL = Counter(
    "agent_gateway_connections_total",
    "WebSocket connection lifecycle events",
    ("event",),
)
RECOVERY_TOTAL = Counter(
    "agent_gateway_recovery_total",
    "WebSocket recovery results",
    ("result",),
)
MESSAGES_TOTAL = Counter(
    "agent_gateway_messages_total",
    "Inbound WebSocket messages",
    ("type",),
)
MESSAGE_LATENCY_SECONDS = Histogram(
    "agent_gateway_message_latency_seconds",
    "Time spent processing a message",
)
TOOL_DURATION_SECONDS = Histogram(
    "agent_gateway_tool_duration_seconds",
    "Time spent executing a tool",
    ("kind",),
)
ERRORS_TOTAL = Counter(
    "agent_gateway_errors_total",
    "Stable gateway errors",
    ("code",),
)
QUOTA_REJECTIONS_TOTAL = Counter(
    "agent_gateway_quota_rejections_total",
    "Quota rejection results",
    ("resource", "code"),
)


def record_authentication(result: str) -> None:
    AUTHENTICATION_TOTAL.labels(result=result).inc()


def record_connection(event: str) -> None:
    CONNECTIONS_TOTAL.labels(event=event).inc()


def record_recovery(result: str) -> None:
    RECOVERY_TOTAL.labels(result=result).inc()


def record_message(message_type: str) -> None:
    MESSAGES_TOTAL.labels(type=message_type).inc()


def observe_message_latency(seconds: float) -> None:
    MESSAGE_LATENCY_SECONDS.observe(seconds)


def observe_tool_duration(kind: str, seconds: float) -> None:
    TOOL_DURATION_SECONDS.labels(kind=kind).observe(seconds)


def record_error(code: str) -> None:
    ERRORS_TOTAL.labels(code=code).inc()


def record_quota_rejection(resource: str, code: str) -> None:
    QUOTA_REJECTIONS_TOTAL.labels(resource=resource, code=code).inc()


def metrics_payload() -> str:
    return generate_latest().decode("utf-8")


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST
