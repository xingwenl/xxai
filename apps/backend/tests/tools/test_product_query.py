"""product_query 商品工具单测：注册契约、未登录、白名单裁剪、排序校验与错误透传。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError
from app.modules.tools.business.registry import get_business_tool


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def _ctx(shop_token=None) -> BusinessToolContext:
    return BusinessToolContext(
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        session=SimpleNamespace(),
        shop_token=shop_token,
        shop_user_id="1",
    )


def _run(args, ctx, monkeypatch, *, response):
    fake = FakeClient(response)

    def fake_client(*a, **kw):
        return fake

    monkeypatch.setattr(
        "app.modules.tools.shop.data.client.httpx.AsyncClient", fake_client
    )
    tool = get_business_tool("product_query")
    assert tool is not None
    result = asyncio.run(tool.handler(args, ctx))
    return result, fake


def _sample_body():
    """product 服务成功码是字符串 "0"，错误信息字段是 message（不是 shop/order 的 msg）。"""
    return {
        "code": "0",
        "message": "总商品池查询成功",
        "data": {
            "list": [
                {
                    "spuId": "2062723964605235297",
                    "libraryId": "2062723874436087809",
                    "libraryName": "总商品池",
                    "name": "【捕捉爱意】19枝红玫瑰花红色系纯玫瑰鲜花束",
                    "mainImage": "http://p0.meituan.net/shangouproductapi/9d90.jpg",
                    "categoryName": "19~21朵",
                    "price": 99.0,
                    "stock": 999,
                    "monthSales": 0,
                    "updatedAt": None,
                    "costPrice": 42.0,
                    "supplierPhone": "13800000000",
                }
            ],
            "total": "1198",
            "pageNum": 1,
            "pageSize": 20,
        },
    }


def test_registered_and_contract():
    tool = get_business_tool("product_query")
    assert tool is not None
    assert tool.input_schema["required"] == []
    properties = tool.input_schema["properties"]
    assert properties["sort_by"]["enum"] == ["monthSales", "price"]
    assert properties["sort_direction"]["enum"] == ["asc", "desc"]
    # 只读工具不涉及审批闸口
    assert tool.side_effect == "none"


def test_not_authenticated_without_token():
    tool = get_business_tool("product_query")
    with pytest.raises(BusinessToolError) as excinfo:
        asyncio.run(tool.handler({}, _ctx()))
    assert excinfo.value.code == "store_ops_not_authenticated"


def test_query_products_success_whitelists_fields(monkeypatch):
    result, fake = _run(
        {
            "page": 2,
            "page_size": 10,
            "keyword": "玫瑰",
            "sort_by": "price",
            "sort_direction": "asc",
        },
        _ctx(shop_token="tok"),
        monkeypatch,
        response=FakeResponse(200, _sample_body()),
    )
    assert result["kind"] == "store_ops_product_list"
    assert result["total"] == 1198  # 字符串总数按 int 解析
    assert result["page"] == 2
    assert result["page_size"] == 10
    product = result["products"][0]
    assert product["spuId"] == "2062723964605235297"
    assert product["name"].startswith("【捕捉爱意】")
    assert product["price"] == 99.0
    # 白名单外的字段（成本价、供应商电话）不下发
    assert "costPrice" not in product
    assert "supplierPhone" not in product
    # 请求参数透传
    params = fake.calls[0][1]["params"]
    assert params["page"] == 2
    assert params["page_size"] == 10
    assert params["keyword"] == "玫瑰"
    assert params["sortBy"] == "price"
    assert params["sortDirection"] == "asc"


def test_query_products_default_sort(monkeypatch):
    _, fake = _run(
        {}, _ctx(shop_token="tok"), monkeypatch, response=FakeResponse(200, _sample_body())
    )
    params = fake.calls[0][1]["params"]
    assert params["sortBy"] == "monthSales"
    assert params["sortDirection"] == "desc"
    assert params["page"] == 1
    assert params["page_size"] == 20
    assert "keyword" not in params  # 不传关键词时不带空参数


def test_query_products_rejects_unsupported_sort():
    tool = get_business_tool("product_query")
    with pytest.raises(BusinessToolError) as excinfo:
        asyncio.run(
            tool.handler({"sort_by": "stock"}, _ctx(shop_token="tok"))
        )
    assert excinfo.value.code == "store_ops_invalid_sort"
    assert "monthSales/price" in excinfo.value.message


def test_query_products_error_passthrough(monkeypatch):
    body = {"code": 401, "message": "认证失败，无法访问系统资源", "data": None}
    with pytest.raises(BusinessToolError) as excinfo:
        _run(
            {},
            _ctx(shop_token="expired"),
            monkeypatch,
            response=FakeResponse(200, body),
        )
    assert excinfo.value.code == "store_ops_api_error"
    assert "认证失败" in excinfo.value.message
