"""shop/ui show_shop_list 工具单测：注册契约、未登录与真实数据渲染块。"""

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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
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


def _run(ctx, monkeypatch, *, response):
    def fake_client(*a, **kw):
        return FakeClient(response)

    monkeypatch.setattr(
        "app.modules.tools.shop.data.client.httpx.AsyncClient", fake_client
    )
    tool = get_business_tool("show_shop_list")
    assert tool is not None
    return asyncio.run(tool.handler({}, ctx))


def test_registered_and_contract():
    tool = get_business_tool("show_shop_list")
    assert tool is not None
    assert tool.input_schema["required"] == []


def test_not_authenticated_without_token():
    tool = get_business_tool("show_shop_list")
    with pytest.raises(BusinessToolError) as excinfo:
        asyncio.run(tool.handler({}, _ctx()))
    assert excinfo.value.code == "store_ops_not_authenticated"


def test_success_returns_shoplist_render_block(monkeypatch):
    body = {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "list": [
                {
                    "id": "2052598884974256130",
                    "platformStoreName": "一世感•轻奢花店",
                    "principalUserName": "花笙",
                    "platformStoreId": "25518721",
                    "tagList": [{"id": "t1", "name": "有花漾代运营"}],
                    "secret": "不应透传",
                }
            ],
            "total": 1,
        },
    }
    result = _run(_ctx(shop_token="tok"), monkeypatch, response=FakeResponse(200, body))
    # ui 层输出 custom 渲染块，SDK 按 component_name=ShopList 驱动前端组件渲染
    assert result["kind"] == "custom"
    assert result["component_name"] == "ShopList"
    assert result["props"]["total"] == 1
    assert "一世感•轻奢花店" in result["fallback"]
    shop = result["props"]["shops"][0]
    assert shop["platformStoreName"] == "一世感•轻奢花店"
    assert shop["principalUserName"] == "花笙"
    assert [tag["name"] for tag in shop["tagList"]] == ["有花漾代运营"]
    assert "secret" not in shop


def test_api_error_passthrough(monkeypatch):
    body = {"code": 401, "msg": "认证失败，无法访问系统资源"}
    with pytest.raises(BusinessToolError) as excinfo:
        _run(
            _ctx(shop_token="expired"),
            monkeypatch,
            response=FakeResponse(401, body),
        )
    assert excinfo.value.code == "store_ops_api_error"
    assert "认证失败" in excinfo.value.message
    assert excinfo.value.status_code == 401
