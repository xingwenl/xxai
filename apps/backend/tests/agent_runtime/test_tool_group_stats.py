"""工具组预取/加载的回放统计：口径、聚合与渲染。"""

from types import SimpleNamespace

from app.modules.agent_runtime.tool_group_stats import (
    STEP_CALL,
    STEP_LOAD,
    observe_run,
    render_markdown,
    summarize,
    tool_schema_chars,
)
from app.modules.agent_runtime.tool_groups import LOAD_TOOL_GROUP_NAME


def _tool(name, *, group, description=None, schema=None):
    return SimpleNamespace(
        name=name,
        kind="builtin",
        group=group,
        description=description or name,
        input_schema={"type": "object", "properties": {}} if schema is None else schema,
    )


def _tools():
    return [
        _tool("ask_user", group="basic"),
        _tool("order_query", group="ops", description="查询订单：读取店铺运营平台数据"),
        _tool("show_shop_list", group="ops", schema={"type": "object", "properties": {"limit": {"type": "integer"}}}),
        _tool("memory_search", group="memory"),
        _tool("remember_user_memory", group="memory"),
        _tool("knowledge_search", group="knowledge"),
    ]


def test_tool_schema_chars_matches_bind_tools_shape():
    """字符数与 bind_tools 载荷一致：外部脚本据此与线上体积对话。"""

    tool = _tool("order_query", group="ops", description="查询订单", schema={})
    # {"type": "function", "function": {...}} 的最小载荷
    assert tool_schema_chars(tool) == len(
        '{"type": "function", "function": {"name": "order_query", '
        '"description": "查询订单", "parameters": {}}}'
    )


def test_observe_run_without_groups_counts_all_tools():
    """工具不足以分组（≤1 组）时线上全量绑定：全部计入首轮体积。"""

    tools = [_tool("only_one", group="ops")]
    observation = observe_run(tools, steps=[(STEP_CALL, "only_one")])

    assert observation["grouped"] is False
    assert observation["tool_calls"] == 1
    assert observation["bound_chars_start"] == observation["bound_chars_max"]
    assert observation["bound_chars_start"] == tool_schema_chars(tools[0])


def test_observe_run_prefetches_groups_from_user_message():
    """预取是纯函数：用同一条用户消息重放，得到与线上一致的初始加载态。"""

    observation = observe_run(_tools(), user_message="帮我看下店铺今天的订单")

    assert observation["prefetched_groups"] == ["ops"]
    # basic 常驻 + 预取的 ops
    assert observation["groups_bound_start"] == 2
    assert observation["bound_chars_start"] > 0
    assert observation["load_calls"] == 0


def test_observe_run_counts_calls_to_unloaded_groups_as_fallback():
    """调用了未加载组的工具＝线上会触发 tool_not_loaded 兜底。"""

    observation = observe_run(_tools(), steps=[(STEP_CALL, "memory_search")])

    assert observation["unbound_calls"] == 1
    assert observation["unbound_tools"] == ["memory_search"]
    assert observation["used_groups"] == ["memory"]


def test_observe_run_replays_loader_call_before_tool_call():
    observation = observe_run(
        _tools(),
        steps=[(STEP_LOAD, "memory"), (STEP_CALL, "remember_user_memory")],
    )

    assert observation["load_calls"] == 1
    assert observation["loaded_groups"] == ["memory"]
    assert observation["unbound_calls"] == 0
    assert observation["wasted_loads"] == 0
    # 加载后绑定体积变大，且不会小于首轮体积
    assert observation["bound_chars_max"] > observation["bound_chars_start"]


def test_observe_run_marks_group_loaded_but_unused_as_wasted():
    observation = observe_run(
        _tools(),
        steps=[
            (STEP_LOAD, "memory"),
            (STEP_LOAD, "ops"),
            (STEP_CALL, "order_query"),
        ],
    )

    assert observation["loaded_groups"] == ["memory", "ops"]
    assert observation["wasted_loads"] == 1


def test_observe_run_ignores_unknown_tool_names():
    """宿主/MCP 工具不在回放清单里：单独计数，不能算成未加载。"""

    observation = observe_run(_tools(), steps=[(STEP_CALL, "ledger_add_entry")])

    assert observation["external_calls"] == 1
    assert observation["unbound_calls"] == 0
    assert observation["used_groups"] == []


def test_summarize_aggregates_rates():
    observations = [
        observe_run(
            _tools(), user_message="看下店铺今天的订单", steps=[(STEP_CALL, "order_query")]
        ),
        observe_run(_tools(), steps=[(STEP_LOAD, "memory"), (STEP_CALL, "memory_search")]),
        observe_run(_tools(), steps=[(STEP_CALL, "knowledge_search")]),
    ]

    stats = summarize(observations)

    assert stats["runs"] == 3
    assert stats["tool_calls"] == 3
    assert stats["avg_tool_calls"] == 1.0
    assert stats["load_calls"] == 1
    assert stats["load_runs"] == 1
    assert stats["load_run_rate"] == round(1 / 3, 4)
    # 首轮预取命中 ops，第三轮 knowledge_search 未加载即调用 → 一次兜底
    assert stats["fallback_runs"] == 1
    assert stats["fallback_rate"] == round(1 / 3, 4)
    assert stats["prefetch_runs"] == 1
    assert stats["prefetch_rate"] == round(1 / 3, 4)
    assert stats["prefetch_useful_runs"] == 1
    assert stats["prefetch_useful_rate"] == 1.0
    # 两个组各有一次加载/调用，按次数排序后并列，内容可读即可
    assert dict(stats["top_loaded_groups"])["memory"] == 1
    assert dict(stats["top_used_groups"])["memory"] == 1
    assert stats["avg_bound_tokens_start"] > 0


def test_summarize_handles_empty_input():
    stats = summarize([])

    assert stats["runs"] == 0
    assert stats["load_run_rate"] == 0.0
    assert stats["top_loaded_groups"] == []


def test_render_markdown_mentions_load_tool_and_volume():
    stats = summarize(
        [observe_run(_tools(), steps=[(STEP_LOAD, "ops"), (STEP_CALL, "order_query")])]
    )

    report = render_markdown(stats)

    assert LOAD_TOOL_GROUP_NAME in report
    assert "运行数：1" in report
    assert "首轮绑定" in report
    assert "ops（1）" in report
