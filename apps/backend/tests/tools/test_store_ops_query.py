"""store_ops_query 业务工具单测：注册契约、未登录/未配置、结果与错误透传。"""

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
    post_bodies: list[dict] = []

    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        FakeClient.post_bodies.append(kwargs.get("json") or {})
        return self.response


def _ctx(shop_token=None, shop_user_id=None) -> BusinessToolContext:
    return BusinessToolContext(
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        session=SimpleNamespace(),
        shop_token=shop_token,
        shop_user_id=shop_user_id,
    )


def _run(args, ctx, monkeypatch, *, response):
    FakeClient.post_bodies.clear()

    def fake_client(*a, **kw):
        return FakeClient(response)

    monkeypatch.setattr(
        "app.modules.tools.shop.data.client.httpx.AsyncClient", fake_client
    )
    tool = get_business_tool("store_ops_query")
    assert tool is not None
    return asyncio.run(tool.handler(args, ctx))


def test_registered_and_contract():
    tool = get_business_tool("store_ops_query")
    assert tool is not None
    assert tool.input_schema["required"] == ["action"]
    assert tool.input_schema["properties"]["action"]["enum"] == ["list_my_shops"]


def test_not_authenticated_without_token():
    tool = get_business_tool("store_ops_query")
    with pytest.raises(BusinessToolError) as excinfo:
        asyncio.run(tool.handler({"action": "list_my_shops"}, _ctx()))
    assert excinfo.value.code == "store_ops_not_authenticated"


def test_list_my_shops_success(monkeypatch):
    body = {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "list": [
                {
                    "id": "2052598884974256130",
                    "platformType": "MT",
                    "platformStoreId": "25518721",
                    "platformStoreName": "一世感•轻奢花店",
                    "principalUserName": "花笙",
                    "businessStatus": 1,
                    "isOnline": 1,
                    "address": "四川省成都市",
                    "tagList": [
                        {"id": "t1", "name": "有花漾代运营", "catalogueName": "商品库"},
                        {"id": "t2", "name": "托管", "catalogueName": "收款方式"},
                    ],
                    "secret": "不应透传",
                }
            ],
            "total": 1,
            "pages": 1,
            "page": 1,
            "page_size": 20,
        },
    }
    result = _run(
        {"action": "list_my_shops"},
        _ctx(shop_token="tok", shop_user_id="1"),
        monkeypatch,
        response=FakeResponse(200, body),
    )
    # data 层只返回数据，不驱动组件渲染（渲染由 shop/ui 的 show_shop_list 负责）
    assert result["kind"] == "store_ops_shop_list"
    assert result["total"] == 1
    assert result["page"] == 1
    assert result["page_size"] == 20
    shop = result["shops"][0]
    assert shop["platformStoreName"] == "一世感•轻奢花店"
    assert shop["principalUserName"] == "花笙"
    assert [tag["name"] for tag in shop["tagList"]] == ["有花漾代运营", "托管"]
    assert "secret" not in shop


def test_list_my_shops_forwards_filters(monkeypatch):
    body = {
        "code": 200,
        "msg": "操作成功",
        "data": {"list": [], "total": 0},
    }
    _run(
        {
            "action": "list_my_shops",
            "platformType": "MT",
            "isOnline": 1,
            "keyword": "花语鲜花",
            "principalUserName": "刘颖",
        },
        _ctx(shop_token="tok"),
        monkeypatch,
        response=FakeResponse(200, body),
    )
    sent = FakeClient.post_bodies[-1]
    assert sent["page"] == 1
    assert sent["page_size"] == 20
    assert sent["platformType"] == "MT"
    assert sent["isOnline"] == 1
    assert sent["keyword"] == "花语鲜花"
    assert sent["principalUserName"] == "刘颖"
    # 未传的筛选参数不出现
    assert "bindStatus" not in sent
    assert "storeIds" not in sent


def test_token_expired_error_passthrough(monkeypatch):
    body = {"code": 401, "msg": "认证失败，无法访问系统资源"}
    with pytest.raises(BusinessToolError) as excinfo:
        _run(
            {"action": "list_my_shops"},
            _ctx(shop_token="expired", shop_user_id="1"),
            monkeypatch,
            response=FakeResponse(401, body),
        )
    assert excinfo.value.code == "store_ops_api_error"
    assert "认证失败" in excinfo.value.message
    assert excinfo.value.status_code == 401


def test_gateway_unreachable(monkeypatch):
    import httpx

    def fake_client(*a, **kw):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(
        "app.modules.tools.shop.data.client.httpx.AsyncClient", fake_client
    )
    tool = get_business_tool("store_ops_query")
    with pytest.raises(BusinessToolError) as excinfo:
        asyncio.run(tool.handler({"action": "list_my_shops"}, _ctx(shop_token="tok")))
    assert excinfo.value.code == "store_ops_gateway_unreachable"
