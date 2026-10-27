"""product_query 商品数据查询工具（shop/data 层）。

用会话级店铺 token 查询店铺运营平台（hua8）总商品池（product-library/all-pool）
的商品数据并返回给模型做文字回答，不驱动任何 UI 渲染；字段按白名单裁剪。
"""

from __future__ import annotations

from app.modules.tools.business.framework import (
    BusinessToolContext,
    business_tool,
)
from app.modules.tools.shop.data.client import fetch_products


@business_tool(
    name="product_query",
    description=(
        "查询商品：读取店铺运营平台（hua8）总商品池（product-library/all-pool）中的"
        "商品数据，用于文字回答「有哪些商品、某个商品的价格/库存/月售/类目、"
        "按销量或价格排序看热门商品」这类问题。"
        "不要用本工具查订单（用 order_query）或店铺（用 store_ops_query）。"
        "用法：当用户询问商品、商品列表、商品池、某商品多少钱、库存多少、卖得怎么样时调用；"
        "keyword 按商品名称模糊搜索（只传商品名关键词，不要带标点或整句）；"
        "sort_by 支持 monthSales（月售）/price（价格），sort_direction 为 asc/desc，"
        "默认按月售倒序；page/page_size 用于翻页。"
        "只读，不会修改、上下架或删除商品。输出规范：按用户问题简洁回答即可，不要渲染卡片。"
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
                "maximum": 100,
                "description": "每页数量，默认 20，上限 100",
            },
            "keyword": {
                "type": "string",
                "maxLength": 100,
                "description": "商品名称关键词（模糊搜索），可选；如“玫瑰”“红玫瑰”",
            },
            "sort_by": {
                "type": "string",
                "enum": ["monthSales", "price"],
                "description": "排序字段：monthSales 月售（默认）/price 价格",
            },
            "sort_direction": {
                "type": "string",
                "enum": ["asc", "desc"],
                "description": "排序方向：desc 倒序（默认）/asc 正序",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
async def product_query(args: dict, ctx: BusinessToolContext) -> dict:
    """按关键词/排序查询总商品池商品；未配置或未登录时返回稳定错误码。"""
    page = int(args.get("page") or 1)
    page_size = int(args.get("page_size") or 20)
    products, total = await fetch_products(
        ctx,
        page=page,
        page_size=page_size,
        keyword=args.get("keyword") or None,
        sort_by=args.get("sort_by") or "monthSales",
        sort_direction=args.get("sort_direction") or "desc",
    )
    return {
        "kind": "store_ops_product_list",
        "total": total,
        "page": page,
        "page_size": page_size,
        "products": products,
    }
