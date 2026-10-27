"""工具组注册表：登记、重复登记与「立即加载」标记。"""

from __future__ import annotations

import pytest

from app.modules.builtin_tool import groups
from app.modules.builtin_tool.groups import (
    EAGER_TOOL_GROUPS,
    TOOL_GROUP_META,
    register_tool_group,
)


@pytest.fixture
def isolated_groups(monkeypatch):
    """隔离全局可变状态：注册表是模块级 dict，用例之间必须互不可见。"""

    monkeypatch.setattr(groups, "TOOL_GROUP_META", dict(TOOL_GROUP_META))
    monkeypatch.setattr(groups, "EAGER_TOOL_GROUPS", set(EAGER_TOOL_GROUPS))


def test_register_tool_group_adds_meta_and_defaults_to_lazy(isolated_groups):
    register_tool_group("demo", "示例", "示例分组")

    assert groups.TOOL_GROUP_META["demo"] == ("示例", "示例分组")
    # 默认异步加载：不进 eager 集合，等 load_tool_group 或预取触发。
    assert "demo" not in groups.EAGER_TOOL_GROUPS


def test_register_tool_group_with_eager_binds_every_turn(isolated_groups):
    register_tool_group("always", "常驻示例", "每轮都绑定", eager=True)

    assert "always" in groups.EAGER_TOOL_GROUPS


def test_register_tool_group_rejects_duplicate_and_blank(isolated_groups):
    register_tool_group("demo2", "示例", "示例分组")

    with pytest.raises(RuntimeError):
        register_tool_group("demo2", "重复", "重复")
    with pytest.raises(ValueError):
        register_tool_group("  ", "空", "空")
    with pytest.raises(ValueError):
        register_tool_group("no_meta", "", "缺标题")
