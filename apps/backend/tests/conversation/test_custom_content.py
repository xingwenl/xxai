"""custom 内容块转换器与 sanitize 协议的单元测试。"""

import asyncio
from types import SimpleNamespace

from app.modules.conversation.runtime import custom_content_blocks
from app.modules.conversation.schemas import sanitize_content_blocks
from app.modules.tools.business.custom_component import show_user_card


def _tool_event(result: dict) -> list[dict]:
    return [{"outcome": SimpleNamespace(result=result)}]


def test_custom_content_blocks_converts_custom_result():
    blocks = custom_content_blocks(
        _tool_event(
            {
                "kind": "custom",
                "component_name": "UserInfoCard",
                "props": {"name": "张三", "email": "zhangsan@example.com"},
                "fallback": "张三 · zhangsan@example.com",
            }
        )
    )
    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "custom"
    assert block["status"] == "completed"
    assert block["component_name"] == "UserInfoCard"
    assert block["props"] == {"name": "张三", "email": "zhangsan@example.com"}
    assert block["fallback"] == "张三 · zhangsan@example.com"


def test_custom_content_blocks_ignores_non_custom_result():
    assert custom_content_blocks(_tool_event({"kind": "image", "assets": []})) == []


def test_custom_content_blocks_ignores_missing_component_name():
    assert custom_content_blocks(_tool_event({"kind": "custom", "fallback": "x"})) == []


def test_custom_content_blocks_defaults_fallback():
    blocks = custom_content_blocks(
        _tool_event({"kind": "custom", "component_name": "FooCard", "props": {}})
    )
    assert blocks[0]["fallback"] == "组件 FooCard 暂不可用"


def test_custom_content_blocks_handles_none_tool_events():
    assert custom_content_blocks(None) == []


def test_sanitize_keeps_component_name_snake_case():
    safe = sanitize_content_blocks(
        [
            {
                "id": "c1",
                "type": "custom",
                "status": "completed",
                "component_name": "UserInfoCard",
                "props": {"name": "张三"},
                "fallback": "张三",
            }
        ]
    )
    assert safe[0]["component_name"] == "UserInfoCard"
    assert "componentName" not in safe[0]


def test_sanitize_rejects_custom_without_fallback():
    safe = sanitize_content_blocks(
        [
            {
                "id": "c2",
                "type": "custom",
                "component_name": "UserInfoCard",
            }
        ]
    )
    assert safe[0]["type"] == "error"


def test_show_user_card_generates_fallback_from_props():
    result = asyncio.run(
        show_user_card({"name": "张三", "email": "zhangsan@example.com"}, None)
    )
    assert result["kind"] == "custom"
    assert result["component_name"] == "UserInfoCard"
    assert result["props"] == {"name": "张三", "email": "zhangsan@example.com"}
    assert result["fallback"] == "张三 · zhangsan@example.com"


def test_show_user_card_fallback_fallback_text():
    result = asyncio.run(show_user_card({}, None))
    assert result["fallback"] == "用户信息暂不可用"
