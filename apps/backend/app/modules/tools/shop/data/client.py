"""店铺运营平台（hua8）数据访问：shop 层工具的公共取数与字段白名单。

只负责用会话级店铺 token 调 hua8 接口并裁剪字段，不做任何 UI 决策；
错误（未配置/未登录/网关不可达/接口错误）统一抛 BusinessToolError，
由 data 与 ui 两层工具按各自语义处理或透传。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
)

# 店铺字段白名单：字段名与 hua8 `shop/platform/list` 响应保持一致。
# 店铺系统响应字段较多，裁剪后避免上下文膨胀与敏感字段外泄。
SHOP_FIELDS = (
    "id",
    "platformType",
    "platformStoreId",
    "platformStoreName",
    "logoUrl",
    "businessStatus",
    "isOnline",
    "address",
    "contactPhone",
    "subjectName",
    "principalUserName",
    "feeRate",
    "authStatus",
    "tagList",
)

# 订单字段白名单：保留运营回答所需字段（店铺/收货人姓名地址/备注/商品/金额），
# 剔除手机号、骑手/发货人电话、op_desc（含打码手机与备注拼接）等隐私字段。
ORDER_FIELDS = (
    "id",
    "platform",
    "app_poi_code",
    "wm_poi_name",
    "day_seq_num",
    "status",
    "ctime",
    "order_id",
    "wm_order_id_view",
    "is_pre_order",
    "delivery_time",
    "order_completed_time",
    "recipient_name",
    "recipient_address",
    "booker_name",
    "comment",
    "user_order_remark",
    "wish",
    "goods",
    "onlinePayment",
    "logisticsFee",
    "wmPoiReceiveCent",
    "productShareFeeChargeByPoi",
    "refund_type",
    "refund_status",
    "refund_amount_total",
)

# 订单商品条目白名单：避免 poster/upc 等无关或易膨胀字段进入上下文。
ORDER_GOODS_FIELDS = ("product_name", "quantity", "price")

# 总商品池字段白名单：字段名与 hua8 `product/lib/all-pool/list` 响应保持一致。
# 主图 URL 可能很长，但仍保留——模型回答“长什么样”时需要它。
PRODUCT_FIELDS = (
    "spuId",
    "libraryId",
    "libraryName",
    "name",
    "mainImage",
    "categoryName",
    "price",
    "stock",
    "monthSales",
    "updatedAt",
)

# 商品列表支持的排序字段（实测 hua8 只对月售与价格生效，其它值会被服务端忽略）。
PRODUCT_SORT_KEYS = ("monthSales", "price")
PRODUCT_SORT_DIRECTIONS = ("asc", "desc")

# 店铺列表接口支持的筛选参数（与 hua8 `shop/platform/list` 入参一致，camelCase）。
# 分页单独用 page/page_size，不在此列。
SHOP_LIST_FILTER_KEYS = (
    "platformType",
    "bindStatus",
    "syncStatus",
    "subjectId",
    "principalUserName",
    "principalUserIds",
    "withoutPrincipal",
    "keyword",
    "tagKeyword",
    "tagIds",
    "withoutTags",
    "businessStatus",
    "isOnline",
    "authStatus",
    "authError",
    "authLimited",
    "platformStoreIds",
    "storeIds",
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _is_success_code(code: object, ok_codes: tuple[int, ...]) -> bool:
    """按数值比较响应码：hua8 的 product 服务把 code 序列化成字符串 "0"。

    不能直接用 `in`——`"0" != 0`，会把成功响应误判成错误。
    """
    try:
        return int(code) in ok_codes
    except (TypeError, ValueError):
        return False


async def _request(
    ctx: BusinessToolContext,
    *,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
    ok_codes: tuple[int, ...] = (200,),
) -> dict:
    """带店铺 token 请求 hua8 并校验响应；错误按店铺系统原样透传。

    hua8 各服务的成功码不统一：shop/order 用 `code: 200`，product 用 `code: 0`
    （且是字符串 "0"），因此成功码由调用方通过 ok_codes 指定，
    避免把正常响应当成错误。
    """
    settings = get_settings()
    if not settings.store_ops_base_url:
        raise BusinessToolError(
            "store_ops_not_configured", message="店铺运营系统未配置，请联系管理员"
        )
    if not ctx.shop_token:
        raise BusinessToolError(
            "store_ops_not_authenticated",
            message="未检测到店铺系统登录，请先登录店铺系统",
        )
    url = settings.store_ops_base_url.rstrip("/") + path
    headers = {"Authorization": f"Bearer {ctx.shop_token}"}
    try:
        async with httpx.AsyncClient(
            timeout=settings.store_ops_http_timeout_seconds
        ) as client:
            if json_body is not None:
                response = await client.post(url, headers=headers, json=json_body)
            else:
                response = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise BusinessToolError(
            "store_ops_gateway_unreachable", message="店铺系统不可达，请稍后重试"
        ) from exc
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    msg = body.get("msg") or body.get("message") if isinstance(body, dict) else None
    if (
        status != 200
        or not isinstance(body, dict)
        or not _is_success_code(body.get("code"), ok_codes)
    ):
        raise BusinessToolError(
            "store_ops_api_error",
            message=f"店铺系统接口返回错误（HTTP {status}）：{msg or '未知错误'}",
            status_code=status,
        )
    return body


def _clean_items(items: list, fields: tuple[str, ...]) -> list[dict]:
    """按字段白名单裁剪响应条目，只保留存在且命名的字段。"""
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned.append({key: item.get(key) for key in fields if key in item})
    return cleaned


async def fetch_my_shops(
    ctx: BusinessToolContext,
    *,
    page: int = 1,
    page_size: int = 20,
    filters: dict | None = None,
) -> tuple[list[dict], int]:
    """查询当前登录用户的店铺列表，返回 (裁剪后的店铺列表, 总数)。

    filters 只允许包含 SHOP_LIST_FILTER_KEYS 内的键，按原样并入请求体，
    用于平台类型、绑定/营业/在线状态、关键词、标签、负责人等筛选。
    """
    payload: dict[str, object] = {"page": page, "page_size": page_size}
    for key in SHOP_LIST_FILTER_KEYS:
        if filters is not None and key in filters:
            payload[key] = filters[key]
    body = await _request(
        ctx,
        path="/hua8-api/shop/platform/list",
        json_body=payload,
    )
    data = body.get("data") or {}
    cleaned = _clean_items(data.get("list") or [], SHOP_FIELDS)
    total = int(data.get("total") or len(cleaned))
    return cleaned, total


def date_to_epoch(date_text: str, *, end_of_day: bool = False) -> int:
    """把 YYYY-MM-DD 转为 hua8 使用的 epoch 秒（Asia/Shanghai 时区）。

    end_of_day=True 表示当天 23:59:59，用于闭区间日期过滤。
    """
    try:
        parsed = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise BusinessToolError(
            "store_ops_invalid_date",
            message=f"日期格式应为 YYYY-MM-DD：{date_text}",
        ) from exc
    if end_of_day:
        local = datetime(
            parsed.year, parsed.month, parsed.day, 23, 59, 59, tzinfo=_SHANGHAI_TZ
        )
    else:
        local = datetime(
            parsed.year, parsed.month, parsed.day, 0, 0, 0, tzinfo=_SHANGHAI_TZ
        )
    return int(local.timestamp())


async def fetch_orders(
    ctx: BusinessToolContext,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    platform_type: str | None = None,
    status: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[dict], int]:
    """查询当前登录用户的订单列表，返回 (裁剪后的订单列表, 总数)。

    默认按下单时间倒序返回最近订单；start_date/end_date 为闭区间日期
    （YYYY-MM-DD），keyword/platform_type/status 均可选过滤。
    """
    params: dict[str, object] = {
        "page": page,
        "size": page_size,
        "sortBy": "ctime",
        "sortDirection": "desc",
    }
    if keyword:
        params["keyword"] = keyword
    if platform_type:
        params["platformType"] = platform_type
    if status is not None:
        params["status"] = status
    if start_date:
        params["startTime"] = date_to_epoch(start_date)
    if end_date:
        params["endTime"] = date_to_epoch(end_date, end_of_day=True)
    body = await _request(
        ctx,
        path="/hua8-api/order/manage/orders",
        params=params,
    )
    data = body.get("data") or {}
    raw_orders = data.get("list") or []
    cleaned = []
    for order in _clean_items(raw_orders, ORDER_FIELDS):
        goods = order.get("goods")
        if isinstance(goods, list):
            order["goods"] = _clean_items(goods, ORDER_GOODS_FIELDS)
        cleaned.append(order)
    try:
        total = int(data.get("total") or len(cleaned))
    except (TypeError, ValueError):
        total = len(cleaned)
    return cleaned, total


async def fetch_products(
    ctx: BusinessToolContext,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    sort_by: str = "monthSales",
    sort_direction: str = "desc",
) -> tuple[list[dict], int]:
    """查询总商品池（product/lib/all-pool）商品，返回 (裁剪后的商品列表, 总数)。

    hua8 该接口只支持 keyword 模糊搜索与排序（月售/价格），没有类目、库、价格
    区间的服务端过滤——传其它参数会被静默忽略，因此这里也不暴露这些入参。
    """
    if sort_by not in PRODUCT_SORT_KEYS:
        raise BusinessToolError(
            "store_ops_invalid_sort",
            message=f"不支持的排序字段：{sort_by}，可选 {'/'.join(PRODUCT_SORT_KEYS)}",
        )
    if sort_direction not in PRODUCT_SORT_DIRECTIONS:
        raise BusinessToolError(
            "store_ops_invalid_sort",
            message=f"不支持的排序方向：{sort_direction}，可选 asc/desc",
        )
    params: dict[str, object] = {
        "page": page,
        "page_size": page_size,
        "sortBy": sort_by,
        "sortDirection": sort_direction,
    }
    if keyword:
        params["keyword"] = keyword
    body = await _request(
        ctx,
        path="/hua8-api/product/lib/all-pool/list",
        params=params,
        # product 服务成功码是 0（不是 shop/order 的 200）。
        ok_codes=(0,),
    )
    data = body.get("data") or {}
    cleaned = _clean_items(data.get("list") or [], PRODUCT_FIELDS)
    try:
        total = int(data.get("total") or len(cleaned))
    except (TypeError, ValueError):
        total = len(cleaned)
    return cleaned, total
