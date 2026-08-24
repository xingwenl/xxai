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

ASK_USER_TOOL = BuiltinToolDefinition(
    name="ask_user",
    description=(
        "向用户提出一个需要其决策的问题，并提供 2-4 个候选选项"
        "（可允许用户输入自定义答案）。"
        "仅在任务范围模糊、需要在方案之间选择或行动前缺少关键信息时调用；"
        "一次只问一个问题；不要用提问替代正常的信息回复。"
        "用户回答后，根据答案继续执行原任务。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
                "description": "要问用户的问题",
            },
            "description": {
                "type": "string",
                "maxLength": 1000,
                "description": "问题的补充说明或背景（可选）",
            },
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 64,
                        },
                        "label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                    },
                    "required": ["id", "label"],
                    "additionalProperties": False,
                },
                "description": "2-4 个候选选项",
            },
            "allowFreeText": {
                "type": "boolean",
                "description": "是否允许用户输入自定义答案，默认 true",
            },
            "requireSelection": {
                "type": "boolean",
                "description": "用户是否必须选择一个选项，默认 true",
            },
        },
        "required": ["question", "options"],
        "additionalProperties": False,
    },
    executor="ask_user",
)

BUILTIN_TOOL_REGISTRY = {
    HTTP_GET_TOOL.name: HTTP_GET_TOOL,
    HTTP_POST_TOOL.name: HTTP_POST_TOOL,
    ASK_USER_TOOL.name: ASK_USER_TOOL,
}


def get_builtin_tool(name: str) -> BuiltinToolDefinition | None:
    return BUILTIN_TOOL_REGISTRY.get(name)


def list_builtin_tools() -> list[BuiltinToolDefinition]:
    return list(BUILTIN_TOOL_REGISTRY.values())
