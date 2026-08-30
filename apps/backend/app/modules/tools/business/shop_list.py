"""show_shop_list 业务工具：示例自定义组件工具，驱动宿主渲染用户店铺列表。

新增自定义组件的标准范式与 custom_component.py 一致：
前端 registerCustomComponent("ShopList", ...) 注册同名组件；
本工具返回 kind=custom 结果，由 conversation/runtime.custom_content_blocks 转换为消息内容块。
"""

from __future__ import annotations

from app.modules.tools.business.framework import (
    BusinessToolContext,
    business_tool,
)

# 店铺条目的 props 白名单，避免模型向组件注入任意字段
_SHOP_FIELDS = ("name", "address", "status", "rating", "url")


@business_tool(
    name="show_shop_list",
    description=(
        "向用户展示其店铺列表（前端渲染为 ShopList 组件）。"
        "用法：当用户要求展示我的店铺、店铺列表、门店列表或商户信息时调用；"
        "从对话上下文或宿主注入的用户数据中提取 shops 数组。"
        "结果使用：组件不可用时前端会展示 fallback 文本，不填则后端根据店铺名自动生成。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shops": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "maxLength": 100,
                            "description": "店铺名称",
                        },
                        "address": {
                            "type": "string",
                            "maxLength": 200,
                            "description": "店铺地址",
                        },
                        "status": {
                            "type": "string",
                            "maxLength": 20,
                            "description": "营业状态，如 营业中/休息中",
                        },
                        "rating": {
                            "type": "number",
                            "maximum": 5,
                            "description": "评分（0-5）",
                        },
                        "url": {
                            "type": "string",
                            "maxLength": 1000,
                            "description": "店铺链接（URL）",
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "description": "店铺列表",
            },
            "fallback": {
                "type": "string",
                "maxLength": 1000,
                "description": "可选兜底文本；不填时后端根据店铺名自动生成",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
async def show_shop_list(args: dict, _ctx: BusinessToolContext) -> dict:
    """清洗店铺字段并返回 custom 结果，交由内容块转换器下发。"""
    raw_shops = args.get("shops") if isinstance(args.get("shops"), list) else []
    shops = []
    for item in raw_shops:
        if not isinstance(item, dict):
            continue
        shop = {key: item[key] for key in _SHOP_FIELDS if key in item}
        if shop.get("name"):
            shops.append(shop)
    fallback = str(args.get("fallback") or "").strip()
    if not fallback:
        names = [str(shop["name"]) for shop in shops]
        fallback = "、".join(names) or "暂无店铺信息"
    return {
        "kind": "custom",
        "component_name": "ShopList",
        "props": {"shops": shops},
        "fallback": fallback,
    }
