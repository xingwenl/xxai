"""order_query 订单工具单测：注册契约、未登录、白名单裁剪与错误透传。"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError
from app.modules.tools.business.registry import get_business_tool
from app.modules.tools.shop.data.client import date_to_epoch


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
    tool = get_business_tool("order_query")
    assert tool is not None
    result = asyncio.run(tool.handler(args, ctx))
    return result, fake


def _sample_body():
    return {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "list": [
                {
                    "id": "893262",
                    "platform": "MT",
                    "wm_poi_name": "格蕾花坊（松山湖店）",
                    "status": 4,
                    "ctime": "1788335977",
                    "order_id": "3402283352459333476",
                    "recipient_name": "吴先生",
                    "recipient_phone": "18575194926_8516",
                    "recipient_address": "东莞市大朗镇兴彩原创花式",
                    "booker_name": "吴先生",
                    "op_desc": "收货人隐私号 18575194926_8516，手机号 157****2731",
                    "comment": "",
                    "onlinePayment": "133.00",
                    "goods": [
                        {
                            "product_id": "yc2604101731",
                            "product_name": "教师节鲜花11枝",
                            "quantity": 1,
                            "price": "139.00",
                            "poster": "https://img.meituan.net/x.jpg",
                        }
                    ],
                    "secret": "不应透传",
                }
            ],
            "total": "2110",
            "pages": "106",
            "page": "1",
            "page_size": "20",
        },
    }


def test_registered_and_contract():
    tool = get_business_tool("order_query")
    assert tool is not None
    assert tool.input_schema["required"] == []
    assert "start_date" in tool.input_schema["properties"]


def test_not_authenticated_without_token():
    tool = get_business_tool("order_query")
    with pytest.raises(BusinessToolError) as excinfo:
        asyncio.run(tool.handler({}, _ctx()))
    assert excinfo.value.code == "store_ops_not_authenticated"


def test_query_orders_success_whitelists_fields(monkeypatch):
    result, fake = _run(
        {"page": 2, "page_size": 10, "platform_type": "MT"},
        _ctx(shop_token="tok"),
        monkeypatch,
        response=FakeResponse(200, _sample_body()),
    )
    assert result["kind"] == "store_ops_order_list"
    assert result["total"] == 2110  # 字符串总数按 int 解析
    assert result["page"] == 2
    assert result["page_size"] == 10
    order = result["orders"][0]
    assert order["order_id"] == "3402283352459333476"
    assert order["recipient_name"] == "吴先生"
    assert order["goods"] == [
        {"product_name": "教师节鲜花11枝", "quantity": 1, "price": "139.00"}
    ]
    # 隐私与无关字段不下发
    assert "recipient_phone" not in order
    assert "op_desc" not in order
    assert "secret" not in order
    # 请求参数透传：page/size/sort 与平台过滤
    assert fake.calls[0][1]["params"]["page"] == 2
    assert fake.calls[0][1]["params"]["size"] == 10
    assert fake.calls[0][1]["params"]["sortBy"] == "ctime"
    assert fake.calls[0][1]["params"]["platformType"] == "MT"


def test_query_orders_date_range_converts_to_epoch(monkeypatch):
    _, fake = _run(
        {"start_date": "2026-09-01", "end_date": "2026-09-01"},
        _ctx(shop_token="tok"),
        monkeypatch,
        response=FakeResponse(200, _sample_body()),
    )
    params = fake.calls[0][1]["params"]
    expected_start = int(
        datetime(2026, 9, 1, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    )
    assert params["startTime"] == expected_start
    assert params["endTime"] == expected_start + 86399
    assert params["startTime"] == date_to_epoch("2026-09-01")
    assert params["endTime"] == date_to_epoch("2026-09-01", end_of_day=True)


def test_query_orders_invalid_date(monkeypatch):
    tool = get_business_tool("order_query")
    with pytest.raises(BusinessToolError) as excinfo:
        asyncio.run(
            tool.handler({"start_date": "2026/09/01"}, _ctx(shop_token="tok"))
        )
    assert excinfo.value.code == "store_ops_invalid_date"


def test_query_orders_error_passthrough(monkeypatch):
    body = {"code": 401, "msg": "认证失败，无法访问系统资源"}
    with pytest.raises(BusinessToolError) as excinfo:
        _run(
            {},
            _ctx(shop_token="expired"),
            monkeypatch,
            response=FakeResponse(401, body),
        )
    assert excinfo.value.code == "store_ops_api_error"
    assert "认证失败" in excinfo.value.message
    assert excinfo.value.status_code == 401
