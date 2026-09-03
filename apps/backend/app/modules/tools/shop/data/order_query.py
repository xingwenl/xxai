"""order_query 订单数据查询工具（shop/data 层）。

用会话级店铺 token 查询店铺运营平台（hua8）的订单数据并返回给模型做文字回答，
不驱动任何 UI 渲染；字段按白名单裁剪，手机号等隐私字段不下发。
"""

from __future__ import annotations

from app.modules.tools.business.framework import (
    BusinessToolContext,
    business_tool,
)
from app.modules.tools.shop.data.client import fetch_orders


@business_tool(
    name="order_query",
    description=(
        "查询店铺运营平台（hua8）中当前用户的订单数据，用于文字回答关于订单的问题，"
        "例如有哪些订单、今日/最近订单、订单状态、收货人、配送与送达时间、备注、"
        "商品与金额等。"
        "用法：当用户询问我的订单、订单列表、今日订单或具体订单信息时调用；"
        "start_date/end_date 为 YYYY-MM-DD 格式的日期区间（都传则查询该区间），"
        "不传默认按下单时间倒序返回最近订单；keyword/platform_type/status 可选过滤。"
        "只读，不会修改订单。输出规范：按用户问题简洁回答即可，不要渲染卡片。"
        "错误语义：店铺系统登录过期或接口报错时，原样透传店铺系统的错误信息，"
        "模型应把该错误如实告知用户（如提示重新登录店铺系统）。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "page": {
                "type": "integer",
                "minimum": 1,
                "description": "页码，默认 1",
            },
            "page_size": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "每页数量，默认 100，上限 1000",
            },
            "keyword": {
                "type": "string",
                "maxLength": 100,
                "description": "关键词过滤（店铺名、订单号等），可选",
            },
            "platform_type": {
                "type": "string",
                "maxLength": 20,
                "description": "平台类型过滤，如 MT（美团），可选",
            },
            "status": {
                "type": "integer",
                "description": "订单状态码过滤，可选",
            },
            "start_date": {
                "type": "string",
                "description": "起始日期 YYYY-MM-DD（含当天），可选",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYY-MM-DD（含当天），可选",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
async def order_query(args: dict, ctx: BusinessToolContext) -> dict:
    """按过滤条件查询当前用户订单；未配置或未登录时返回稳定错误码。"""
    page = int(args.get("page") or 1)
    page_size = int(args.get("page_size") or 20)
    orders, total = await fetch_orders(
        ctx,
        page=page,
        page_size=page_size,
        keyword=args.get("keyword") or None,
        platform_type=args.get("platform_type") or None,
        status=args.get("status"),
        start_date=args.get("start_date") or None,
        end_date=args.get("end_date") or None,
    )
    return {
        "kind": "store_ops_order_list",
        "total": total,
        "page": page,
        "page_size": page_size,
        "orders": orders,
    }
