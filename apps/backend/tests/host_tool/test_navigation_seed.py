from scripts.seed_demo_host_tools import DEMO_TOOLS


def test_demo_seed_includes_internal_navigation_tool():
    navigation = next(
        item for item in DEMO_TOOLS if item["name"] == "navigate_to_page"
    )

    assert navigation["side_effect"] == "navigation"
    assert navigation["confirmation_policy"] == "always"
    assert navigation["input_schema"]["required"] == ["page_name"]
    assert (
        navigation["input_schema"]["properties"]["page_name"]["description"]
        == "页面名称，例如“智能体管理”或“模型用量”"
    )
