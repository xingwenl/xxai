from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BuiltinToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    executor: str
    kind: str = "builtin"
    side_effect: str = "none"


HTTP_GET_TOOL = BuiltinToolDefinition(
    name="http_get",
    description=(
        "读取一个公开的 HTTP 或 HTTPS URL。仅发送无认证信息的 GET 请求；"
        "JSON 和文本直接返回，图片与其他文件返回受控资源引用。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2048,
                "description": "要读取的公开 HTTP 或 HTTPS URL",
            }
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    executor="http_get",
)

HTTP_POST_TOOL = BuiltinToolDefinition(
    name="http_post",
    description=(
        "向一个公开的 HTTP 或 HTTPS URL 发送 POST 请求（可选 JSON 请求体）。"
        "JSON 和文本直接返回；适合调用需要 POST 的公开 API。"
        "注意：这是无认证的公开请求，不要用来发送敏感信息。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2048,
                "description": "要请求的公开 HTTP 或 HTTPS URL",
            },
            "body": {
                "type": "object",
                "description": "要发送的 JSON 请求体（可选，默认空对象）",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    executor="http_post",
)

BUILTIN_TOOL_REGISTRY = {
    HTTP_GET_TOOL.name: HTTP_GET_TOOL,
    HTTP_POST_TOOL.name: HTTP_POST_TOOL,
}


def get_builtin_tool(name: str) -> BuiltinToolDefinition | None:
    return BUILTIN_TOOL_REGISTRY.get(name)


def list_builtin_tools() -> list[BuiltinToolDefinition]:
    return list(BUILTIN_TOOL_REGISTRY.values())
