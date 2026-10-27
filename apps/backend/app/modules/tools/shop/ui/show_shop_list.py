"""show_shop_list 店铺列表展示工具（shop/ui 层）。

仅当用户明确要求「展示/查看我的店铺列表」时渲染 ShopList 卡片：
数据来自店铺运营平台（hua8）真实接口（复用 shop/data 的 fetch_my_shops），
不允许模型编造店铺数据；返回 kind=custom 渲染块，由 runtime 转为消息内容块，
SDK 侧注册同名 ShopList 组件后渲染，未注册时展示 fallback 文本。
"""

from __future__ import annotations

from app.modules.tools.business.framework import (
    BusinessToolContext,
    business_tool,
)
from app.modules.tools.shop.data.client import fetch_my_shops


def _build_fallback(shops: list[dict], total: int) -> str:
    """根据真实店铺名生成可读兜底文本，组件不可用或未注册时仍能看到摘要。"""
    names = [
        str(shop["platformStoreName"])
        for shop in shops
        if str(shop.get("platformStoreName") or "").strip()
    ]
    if not names:
        return "暂无店铺信息"
    head = "、".join(names[:3])
    if len(names) > 3:
        return f"{head} 等 {len(names)} 家店铺"
    if total > len(names):
        return f"{head} 共 {total} 家店铺"
    return head


@business_tool(
    name="show_shop_list",
    description=(
        "展示店铺卡片：把当前用户的店铺列表以 ShopList 卡片形式渲染给用户。"
        "只要文字回答（有哪些店、店铺 ID、负责人、地址等）就用 store_ops_query，"
        "不要用本工具。"
        "用法：仅当用户明确要求「展示/查看我的店铺、店铺列表、门店列表或有哪些店」时调用；"
        "内部会自动读取店铺系统登录态并查询真实数据，不需要也不能由模型传入店铺数据。"
        "输出规范：调用成功后只给一行总览（例如「共 N 家店铺，见下方卡片」），"
        "不要逐条复述卡片里的名称、地址或标签。"
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
                "maximum": 50,
                "description": "每页数量，默认 20，上限 50",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
async def show_shop_list(args: dict, ctx: BusinessToolContext) -> dict:
    """查询并渲染当前用户的店铺列表卡片；未配置或未登录时返回稳定错误码。"""
    page = int(args.get("page") or 1)
    page_size = int(args.get("page_size") or 20)
    shops, total = await fetch_my_shops(ctx, page=page, page_size=page_size)
    return {
        "kind": "custom",
        "component_name": "ShopList",
        # props.shops 条目字段名与 hua8 平台一致（platformStoreName 等），
        # 前端 ShopList 组件直接按原字段渲染；total 供组件判断是否还有更多。
        "props": {"shops": shops, "total": total},
        "fallback": _build_fallback(shops, total),
    }
