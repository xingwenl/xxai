import pytest

from app.modules.agent_runtime.tools import ToolCatalog


def test_catalog_indexes_named_tools():
    first = type("Tool", (), {"name": "search"})()
    catalog = ToolCatalog([first])

    assert catalog.get("search") is first
    assert catalog.names() == ("search",)


def test_catalog_rejects_duplicate_tool_names():
    with pytest.raises(ValueError, match="duplicate runtime tool name"):
        ToolCatalog(
            [
                type("Tool", (), {"name": "search"})(),
                type("Tool", (), {"name": "search"})(),
            ]
        )
