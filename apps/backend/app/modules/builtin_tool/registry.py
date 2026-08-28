"""内置工具对外契约注册表：从业务工具注册表派生，保持旧链路契约不变。

描述与 input_schema 的单一事实来源在 `tools/business`（业务工具定义与 handler 同页）；
此处只把业务工具包装成旧链路（管理端目录、Agent 绑定、运行时委托）可消费的
`BuiltinToolDefinition`，避免两处重复维护造成契约漂移。
`ask_user` 由网关直连处理，没有业务 handler，单独维护。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.modules.tools.business.framework import BusinessTool, BusinessToolContext
from app.modules.tools.business.registry import list_business_tools

BusinessToolHandler = Callable[[dict, BusinessToolContext], Awaitable[dict]]


@dataclass(frozen=True)
class BuiltinToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    executor: BusinessToolHandler | None
    kind: str = "builtin"
    side_effect: str = "none"


def _from_business(tool: BusinessTool) -> BuiltinToolDefinition:
    """把业务工具包装成旧链路可消费的对外定义。"""
    return BuiltinToolDefinition(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        executor=tool.handler,
    )


ASK_USER_TOOL = BuiltinToolDefinition(
    name="ask_user",
    description=(
        "向用户提出一个需要其决策的问题，并提供 2-4 个候选选项"
        "（可允许用户输入自定义答案）。"
        "用法：仅在任务范围模糊、需要在方案之间选择或行动前缺少关键信息时调用；"
        "一次只问一个问题，question 必填，options 必须提供 2-4 个选项。"
        "结果使用：用户的回答会在后续轮次以工具结果返回，拿到答案后继续执行原任务；"
        "不要用提问替代正常信息回复，也不要重复提问同一问题。"
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
    executor=None,  # ask_user 由网关直连处理，不注册业务 handler
)

# 业务工具自动纳入目录：新增工具只需在 tools/business 完成注册（含收集页 import），
# 此处无需任何改动；ask_user 是网关直连特例，单独追加。
BUILTIN_TOOL_REGISTRY = {
    tool.name: _from_business(tool) for tool in list_business_tools()
}
BUILTIN_TOOL_REGISTRY[ASK_USER_TOOL.name] = ASK_USER_TOOL


def get_builtin_tool(name: str) -> BuiltinToolDefinition | None:
    return BUILTIN_TOOL_REGISTRY.get(name)


def list_builtin_tools() -> list[BuiltinToolDefinition]:
    return list(BUILTIN_TOOL_REGISTRY.values())
