"""show_user_card 业务工具：示例自定义组件工具，驱动宿主渲染用户信息卡片。

新增自定义组件的标准范式（流程固定，方便后续扩展）：
1. 前端：编写 Vue 组件并调用 registerCustomComponent("<组件名>", Component) 注册；
2. 后端：复制本文件，按同样结构新增一个 @business_tool 装饰的业务工具，
   返回 {"kind": "custom", "component_name": "<组件名>", "props": {...}, "fallback": "..."}；
3. 注册页：在 tools/business/registry.py 中 import 新模块（导入即注册）；
4. 启用：在管理端为对应 Agent 启用该内置工具；
5. 验证：对话触发后，SDK 渲染已注册组件，未注册时展示 fallback。

结果转换：kind=custom 的结果由 conversation/runtime.custom_content_blocks
转换为消息内容块，协议字段统一使用 component_name（snake_case）。
"""

from __future__ import annotations

from app.modules.tools.business.framework import (
    BusinessToolContext,
    business_tool,
)

# 用户信息卡片的 props 白名单，避免模型向组件注入任意字段
_CARD_FIELDS = ("name", "email", "avatar", "title", "department", "summary")


@business_tool(
    name="show_user_card",
    description=(
        "向用户展示一张用户信息卡片（前端渲染为 UserInfoCard 组件）。"
        "用法：当用户要求展示自己的信息、用户资料、名片或个人简介时调用；"
        "从对话上下文或宿主注入的用户信息中提取字段填入参数。"
        "结果使用：组件不可用时前端会展示 fallback 文本，因此 fallback 必须包含"
        "可读的信息摘要，不得留空。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "maxLength": 100,
                "description": "姓名",
            },
            "email": {
                "type": "string",
                "maxLength": 200,
                "description": "邮箱",
            },
            "avatar": {
                "type": "string",
                "maxLength": 1000,
                "description": "头像图片地址（URL）",
            },
            "title": {
                "type": "string",
                "maxLength": 100,
                "description": "职位或头衔",
            },
            "department": {
                "type": "string",
                "maxLength": 100,
                "description": "部门或团队",
            },
            "summary": {
                "type": "string",
                "maxLength": 500,
                "description": "一句话简介",
            },
            "fallback": {
                "type": "string",
                "maxLength": 1000,
                "description": "可选兜底文本；不填时后端根据已填字段自动生成，组件不可用时不至于空白",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
async def show_user_card(args: dict, _ctx: BusinessToolContext) -> dict:
    """从模型参数中提取卡片字段并返回 custom 结果，交由内容块转换器下发。"""
    props = {key: args[key] for key in _CARD_FIELDS if args.get(key)}
    fallback = str(args.get("fallback") or "").strip()
    if not fallback:
        fallback = " · ".join(
            str(props[key]) for key in ("name", "title", "email") if props.get(key)
        ) or "用户信息暂不可用"
    return {
        "kind": "custom",
        "component_name": "UserInfoCard",
        "props": props,
        "fallback": fallback,
    }
