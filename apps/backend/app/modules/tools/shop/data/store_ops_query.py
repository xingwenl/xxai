"""store_ops_query 店铺数据查询工具（shop/data 层）。

用会话级店铺 token 查询店铺运营平台（hua8）数据并返回给模型做文字回答，
不驱动任何 UI 渲染；需要把店铺列表展示为 ShopList 卡片时，模型应改调
shop/ui 层的 show_shop_list 工具。
"""

from __future__ import annotations

from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
    business_tool,
)
from app.modules.tools.shop.data.client import SHOP_LIST_FILTER_KEYS, fetch_my_shops


@business_tool(
    name="store_ops_query",
    description=(
        "查询店铺运营平台（hua8）中当前用户的店铺数据，用于文字回答关于店铺的"
        "具体问题（有哪些店、店铺 ID、负责人、标签、地址、联系方式、营业状态等）。"
        "用法：当用户询问我的店铺、门店、商户相关信息并期望得到信息回答时调用；"
        "可用筛选条件缩小范围，例如只查美团（platformType=MT）、只看在售店铺"
        "（isOnline=1）、按店铺名/关键词搜索（keyword）或按负责人（principalUserName）等。"
        "数据来自店铺系统当前登录用户会话，只读，不会修改店铺数据。"
        "输出规范：按用户问题给出简洁回答，需要列出多店时用短列表即可，不要渲染卡片。"
        "注意：当用户明确要求「展示/查看我的店铺列表（卡片）」时，应调用 show_shop_list"
        "工具渲染 ShopList 卡片，不要使用本工具输出卡片。"
        "错误语义：店铺系统登录过期或接口报错时，原样透传店铺系统的错误信息，"
        "模型应把该错误如实告知用户（如提示重新登录店铺系统）。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_my_shops"],
                "description": "操作类型，当前仅支持 list_my_shops（查询我的店铺）",
            },
            "page": {
                "type": "integer",
                "minimum": 1,
                "description": "页码，默认 1",
            },
            "page_size": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "每页数量，默认 20，上限 1000",
            },
            "platformType": {
                "type": "string",
                "maxLength": 20,
                "description": "平台类型，如 MT（美团）、TB（淘宝），可选",
            },
            "bindStatus": {
                "type": "integer",
                "description": "绑定状态码过滤，可选",
            },
            "syncStatus": {
                "type": "integer",
                "description": "同步状态码过滤，可选",
            },
            "subjectId": {
                "type": "integer",
                "description": "主体 ID 过滤，可选",
            },
            "principalUserName": {
                "type": "string",
                "maxLength": 50,
                "description": "负责人姓名过滤，可选",
            },
            "principalUserIds": {
                "type": "string",
                "maxLength": 200,
                "description": "负责人 ID 列表（逗号分隔），可选",
            },
            "withoutPrincipal": {
                "type": "boolean",
                "description": "是否只查无负责人的店铺，可选",
            },
            "keyword": {
                "type": "string",
                "maxLength": 100,
                "description": "关键词过滤（店铺名等），可选",
            },
            "tagKeyword": {
                "type": "string",
                "maxLength": 50,
                "description": "标签关键词过滤，可选",
            },
            "tagIds": {
                "type": "string",
                "maxLength": 500,
                "description": "标签 ID 列表（逗号分隔），可选",
            },
            "withoutTags": {
                "type": "boolean",
                "description": "是否只查无标签的店铺，可选",
            },
            "businessStatus": {
                "type": "integer",
                "description": "营业状态码过滤，可选",
            },
            "isOnline": {
                "type": "integer",
                "description": "平台在线状态过滤（1 在售/0 非在售），可选",
            },
            "authStatus": {
                "type": "integer",
                "description": "授权状态码过滤，可选",
            },
            "authError": {
                "type": "boolean",
                "description": "是否只查授权异常的店铺，可选",
            },
            "authLimited": {
                "type": "boolean",
                "description": "是否只查授权受限的店铺，可选",
            },
            "platformStoreIds": {
                "type": "string",
                "maxLength": 1000,
                "description": "平台店铺 ID 列表（逗号分隔，如 MT10001），可选",
            },
            "storeIds": {
                "type": "string",
                "maxLength": 1000,
                "description": "系统店铺 ID 列表（逗号分隔），可选",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
)
async def store_ops_query(args: dict, ctx: BusinessToolContext) -> dict:
    """按 action 分发店铺查询；未配置或未登录时返回稳定错误码。"""
    action = args.get("action")
    if action == "list_my_shops":
        page = int(args.get("page") or 1)
        page_size = int(args.get("page_size") or 20)
        filters = {key: args[key] for key in SHOP_LIST_FILTER_KEYS if key in args}
        shops, total = await fetch_my_shops(
            ctx, page=page, page_size=page_size, filters=filters or None
        )
        return {
            "kind": "store_ops_shop_list",
            "total": total,
            "page": page,
            "page_size": page_size,
            "shops": shops,
        }
    raise BusinessToolError(
        "store_ops_invalid_action", message=f"不支持的操作：{action}"
    )
