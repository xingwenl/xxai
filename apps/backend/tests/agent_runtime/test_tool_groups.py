"""工具按组按需加载：分组判定、加载状态、兜底与重绑。"""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.modules.agent_runtime.composition import (
    build_langchain_runtime,
    make_legacy_tool_invoker,
)
from app.modules.agent_runtime.contracts import ToolCall
from app.modules.agent_runtime.langchain_adapter import LangChainModelInvoker
from app.modules.agent_runtime.tool_groups import (
    LOAD_TOOL_GROUP_NAME,
    ToolGroupState,
    build_tool_group_state,
    group_meta,
    tool_group,
)
from app.modules.builtin_tool.registry import ASK_USER_TOOL, list_builtin_tools


def _tool(name, *, group=None, kind="builtin", server_id=None):
    """构造测试用工具；未声明 group 时走来源推导分支。"""

    attrs = {"name": name, "kind": kind, "description": name, "input_schema": {}}
    if group is not None:
        attrs["group"] = group
    if server_id is not None:
        attrs["server_id"] = server_id
    return SimpleNamespace(**attrs)


def _grouped_tools():
    return [
        _tool("ask_user", group="basic"),
        _tool("order_query", group="ops"),
        _tool("show_shop_list", group="ops"),
        _tool("memory_search", group="memory"),
        _tool("ledger_add_entry", kind="host"),
        _tool("note_save", kind="host"),
    ]


def test_tool_group_prefers_declared_group_then_source_attributes():
    assert tool_group(_tool("order_query", group="ops")) == "ops"
    assert tool_group(_tool("lookup", kind="mcp", server_id=7)) == "mcp:7"
    assert tool_group(_tool("run_skill_script", kind="skill_script")) == "skill"
    # 已登记前缀的宿主工具按子应用成组。
    assert tool_group(_tool("ledger_add_entry", kind="host")) == "ledger"
    assert tool_group(_tool("note_save_note", kind="host")) == "note"
    assert tool_group(_tool("page_click", kind="host")) == "page"
    # 未登记的前缀不按首段猜组名，统一归 host：否则目录里会冒出 debug、get、
    # navigate 这种「一个工具一个组」的噪音条目。
    assert tool_group(_tool("debug_ping", kind="host")) == "host"
    assert tool_group(_tool("get_weather", kind="host")) == "host"
    assert tool_group(_tool("navigate_to_page", kind="host")) == "host"
    # 没有下划线的宿主工具同样归到 host 组。
    assert tool_group(_tool("snapshot", kind="host")) == "host"


def test_host_group_meta_covers_registered_prefixes():
    """已登记前缀要有可读标题，未登记前缀仍回落「页面」说明。"""

    assert group_meta("note")[0] == "念记"
    assert group_meta("ledger")[0] == "记账"
    assert group_meta("page")[0] == "页面操作"
    assert group_meta("host") == ("页面", "页面宿主注册的工具")


def test_single_group_keeps_legacy_behaviour():
    tools = [_tool("ask_user", group="basic"), _tool("order_query", group="ops")]

    assert build_tool_group_state(tools) is not None
    # 只有一个非常驻组时，按需加载没有任何可选性，直接退回旧行为。
    assert build_tool_group_state([_tool("order_query", group="ops")]) is None
    assert build_tool_group_state(tools, enabled=False) is None


def test_initial_binding_only_holds_basic_tools_and_loader():
    state = ToolGroupState(_grouped_tools())

    names = [tool.name for tool in state.bound_tools()]

    assert names == ["ask_user", LOAD_TOOL_GROUP_NAME]
    assert state.pending_groups() == ["ledger", "memory", "note", "ops"]


def test_loader_schema_enumerates_pending_groups_only():
    state = ToolGroupState(_grouped_tools())
    loader = state.loader_tool()

    assert loader.input_schema["required"] == ["group"]
    assert loader.input_schema["properties"]["group"]["enum"] == state.pending_groups()
    assert "ops" in loader.description


def test_catalog_lists_group_meta_and_tool_names():
    state = ToolGroupState(_grouped_tools())
    catalog = state.catalog_text()

    assert "工具目录" in catalog
    assert "ops（运营）" in catalog
    assert "order_query" in catalog
    # 常驻工具不写进目录：它们已经在上下文里了。
    assert "ask_user" not in catalog


def test_activate_is_idempotent_and_monotonic():
    state = ToolGroupState(_grouped_tools())

    first = state.activate("ops")
    version_after_first = state.version
    second = state.activate("ops")

    assert sorted(first) == ["order_query", "show_shop_list"]
    assert second == []
    assert state.version == version_after_first
    assert "ops" not in state.pending_groups()
    assert "order_query" in [tool.name for tool in state.bound_tools()]


def test_loader_disappears_once_every_group_is_loaded():
    state = ToolGroupState(_grouped_tools())

    state.activate_all()

    assert state.loader_tool() is None
    assert state.catalog_text() is None
    assert LOAD_TOOL_GROUP_NAME not in [tool.name for tool in state.bound_tools()]


def test_loader_call_reports_completed_and_unknown_group():
    state = ToolGroupState(_grouped_tools())

    done = state.handle_loader_call({"group": "ops"})
    unknown = state.handle_loader_call({"group": "nope"})
    missing = state.handle_loader_call({})

    assert done["status"] == "completed"
    assert done["result"]["loaded_group"] == "ops"
    assert unknown["status"] == "failed"
    assert unknown["error"]["code"] == "tool_group_unknown"
    assert missing["error"]["code"] == "tool_group_required"


def test_invoker_intercepts_loader_without_touching_business_callback():
    state = ToolGroupState(_grouped_tools())
    calls = []

    async def callback(**kwargs):
        calls.append(kwargs["tool"].name)
        return {"status": "completed", "result": "ok"}

    async def run():
        invoke = make_legacy_tool_invoker(
            state.all_tools, callback, group_state=state
        )
        return await invoke(
            ToolCall(id="c1", name=LOAD_TOOL_GROUP_NAME, arguments={"group": "ops"})
        )

    outcome = asyncio.run(run())

    assert outcome.status == "completed"
    assert calls == []


def test_calling_unloaded_tool_activates_all_groups_and_asks_for_retry():
    state = ToolGroupState(_grouped_tools())
    calls = []

    async def callback(**kwargs):
        calls.append(kwargs["tool"].name)
        return {"status": "completed", "result": "ok"}

    async def run():
        invoke = make_legacy_tool_invoker(
            state.all_tools, callback, group_state=state
        )
        first = await invoke(
            ToolCall(id="c1", name="memory_search", arguments={"q": "x"})
        )
        second = await invoke(
            ToolCall(id="c2", name="memory_search", arguments={"q": "x"})
        )
        return first, second

    first, second = asyncio.run(run())

    assert first.status == "failed"
    assert first.error["code"] == "tool_not_loaded"
    assert LOAD_TOOL_GROUP_NAME in first.error["message"]
    # 兜底的关键：失败一次之后同一个调用必须能成功，否则模型没有恢复路径。
    assert second.status == "completed"
    assert calls == ["memory_search"]
    assert state.pending_groups() == []


def test_unknown_tool_still_reports_tool_not_found():
    state = ToolGroupState(_grouped_tools())

    async def callback(**kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("callback should not run")

    async def run():
        invoke = make_legacy_tool_invoker(
            state.all_tools, callback, group_state=state
        )
        return await invoke(ToolCall(id="c1", name="ghost", arguments={}))

    outcome = asyncio.run(run())

    assert outcome.status == "failed"
    assert outcome.error["code"] == "tool_not_found"


class _RecordingModel:
    """记录每次绑定的工具名，用于验证「加载后重绑」。"""

    def __init__(self):
        self.bound_names = []

    def bind_tools(self, tools):
        self.bound_names.append([item["function"]["name"] for item in tools])
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="ok")


def test_model_invoker_rebinds_after_group_load():
    state = ToolGroupState(_grouped_tools())
    model = _RecordingModel()
    invoker = LangChainModelInvoker(model, state.all_tools, tool_group_state=state)

    assert model.bound_names[-1] == ["ask_user", LOAD_TOOL_GROUP_NAME]

    state.activate("ops")
    asyncio.run(invoker([], emit=_noop_emit, allow_tools=False))

    assert model.bound_names[-1] == ["ask_user", "order_query", "show_shop_list", LOAD_TOOL_GROUP_NAME]


async def _noop_emit(event):
    return None


def test_runtime_composition_enables_groups_only_when_asked():
    tools = _grouped_tools()
    model = _RecordingModel()

    build_langchain_runtime(
        model, tools, _noop_callback, streaming=False, enable_tool_groups=False
    )
    # 关闭分组时仍是旧行为：一次绑定全部工具。
    assert model.bound_names[-1] == [tool.name for tool in tools]

    build_langchain_runtime(
        model, tools, _noop_callback, streaming=False, enable_tool_groups=True
    )
    assert model.bound_names[-1] == ["ask_user", LOAD_TOOL_GROUP_NAME]


async def _noop_callback(**kwargs):  # pragma: no cover - 不在本测试路径
    raise AssertionError("not used")


def test_builtin_registry_tools_are_grouped():
    """真实内置工具必须全部登记分组，且首轮绑定远小于全量。"""

    tools = list(list_builtin_tools())
    state = build_tool_group_state(tools)

    assert state is not None
    assert all(getattr(tool, "group", "") for tool in tools)
    assert ASK_USER_TOOL.group == "basic"
    assert len(state.bound_tools()) < len(tools)
    assert "ops" in state.pending_groups()
