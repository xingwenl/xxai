"""宿主工具分组声明：连接级容器，非法声明只忽略、不影响注册。"""

from __future__ import annotations

from app.modules.host_tool.services import HostToolGroupDeclarations


def test_declare_tool_and_group():
    declarations = HostToolGroupDeclarations()

    declarations.declare_tool("note_create_note", "notes")
    declarations.declare_group("notes", " 笔记 ", "用户自己的笔记", eager=True)

    assert declarations.groups == {"note_create_note": "notes"}
    assert declarations.group_meta == {"notes": ("笔记", "用户自己的笔记")}
    assert declarations.eager_groups == {"notes"}


def test_group_defaults_to_lazy_and_meta_falls_back_to_name():
    declarations = HostToolGroupDeclarations()

    declarations.declare_group("ledger")

    assert declarations.eager_groups == set()
    assert declarations.group_meta == {"ledger": ("ledger", "ledger")}


def test_illegal_declarations_are_ignored():
    declarations = HostToolGroupDeclarations()

    declarations.declare_tool(None, "notes")
    declarations.declare_tool("tool", None)
    declarations.declare_tool("tool", "   ")
    declarations.declare_group(123)
    declarations.declare_group("  ")

    assert declarations.groups == {}
    assert declarations.group_meta == {}
    assert declarations.eager_groups == set()
