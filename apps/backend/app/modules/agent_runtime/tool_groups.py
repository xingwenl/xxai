"""按组按需加载工具：只决定「本轮绑定哪些工具」，不改任何工具语义。

设计要点（对应 docs/harness/requests/2026-10-27-tool-groups-lazy-load/spec.md）：

- 分组是**工具侧常量**（内置工具见 ``builtin_tool/groups.py``，宿主工具按名称
  前缀、MCP 按 server_id 推导），与用户意图无关，也不需要分类器参与。
- 常驻的只有两样：系统提示词里的工具目录（``catalog_text``）和
  ``load_tool_group`` 工具本身。
- 加载**单调只增**：一旦加载，会话内不再卸载，因此前缀缓存最多每组失效一次，
  而不是每轮失效。
- 加载态**不落库**：它由本会话历史上 ``load_tool_group`` 的调用记录重放得到
  （见 :meth:`ToolGroupState.restore`），所以同一段历史必然推出同一个工具集合，
  续跑与重放都能复现，不需要额外的状态列或状态机。
- 兜底必须存在：模型直接调用未加载的工具时，调用器会 ``activate_all()`` 并
  回填可重试的提示，避免出现“工具不在上下文里、模型永远没有机会”的死局。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.modules.agent_runtime.tool_prefetch import prefetch_tool_groups
from app.modules.builtin_tool.groups import (
    BASIC_GROUP,
    EAGER_TOOL_GROUPS,
    TOOL_GROUP_META,
)

# 按需加载工具名：与 load_skill 同一套「常驻目录 + 按需加载」范式。
LOAD_TOOL_GROUP_NAME = "load_tool_group"

# 加载结果里携带「这次加载了哪一组」的元数据键。工具结果的 ``metadata`` 会被
# 工具步骤落库到 ``agent_loop_steps.step_metadata``，下一轮靠它重放加载态——
# 不去解析面向用户的 ``output_summary`` 文本。
LOADED_GROUP_METADATA_KEY = "tool_group"

# 宿主工具名前缀无法识别时的兜底组名。
HOST_GROUP = "host"

# 宿主工具按名称前缀分组：页面注册链路不携带分组信息（入站契约
# ``HostToolRegistration`` 只有 name/description/input_schema），所以只能按命名
# 约定推导。**只认登记过的前缀**——未登记的一律归 ``host``，避免 ``debug_ping``、
# ``get_weather``、``navigate_to_page`` 这类名字按首段凭空造出 debug、get、
# navigate 组，把一个工具的组塞进工具目录。
HOST_TOOL_GROUP_PREFIXES: dict[str, str] = {
    "note": "note",
    "ledger": "ledger",
    "page": "page",
}

# 宿主工具组的展示信息：组名 →（标题，一句话说明）。
_HOST_GROUP_META: dict[str, tuple[str, str]] = {
    "note": ("念记", "念记笔记子应用注册的方法"),
    "ledger": ("记账", "记账子应用注册的方法"),
    "page": ("页面操作", "当前页面注册的通用页面操作工具"),
}

# 兜底提示：模型调用了未加载的工具时返回，明确要求它重试同一次调用。
RETRY_HINT = "工具组已全部加载，请立即重试刚才的工具调用，不需要再调用 {loader}。"


def tool_group(tool: Any, host_groups: Mapping[str, str] | None = None) -> str:
    """判定工具所属分组：优先工具自身声明，其次按来源形态推导。

    内置业务工具带 ``group`` 字段；宿主（页面）工具的分组由连接注册时声明，
    落在 ``host_groups``（工具名 → 组名）；MCP 工具带 ``server_id``；技能脚本/
    指令工具带 ``kind``；最后才按「子应用_动作」的登记前缀归组。
    """

    declared = getattr(tool, "group", None)
    if isinstance(declared, str) and declared:
        return declared
    name = str(getattr(tool, "name", "") or "")
    if host_groups and name in host_groups:
        return host_groups[name]
    server_id = getattr(tool, "server_id", None)
    if server_id is not None:
        return f"mcp:{server_id}"
    kind = str(getattr(tool, "kind", "") or "")
    if kind.startswith("skill"):
        return "skill"
    return _host_group(str(getattr(tool, "name", "") or ""))


def _host_group(name: str) -> str:
    """宿主工具按**登记过的**名称前缀分组：``ledger_add_entry`` → ``ledger``。

    前缀未登记（含没有分隔符的名字，如 ``snapshot``）时统一归 ``host``，
    不按首段猜组名——猜出来的组名只是噪音，还会让目录里多出无意义的条目。
    """

    head = name.split("_", 1)[0].split(".", 1)[0]
    return HOST_TOOL_GROUP_PREFIXES.get(head, HOST_GROUP)


def group_meta(
    group: str, host_group_meta: Mapping[str, tuple[str, str]] | None = None
) -> tuple[str, str]:
    """分组展示信息：返回（标题，一句话说明），未知组按名称原样展示。

    ``host_group_meta`` 是宿主连接注册时声明的组元数据（组名 →（标题，说明）），
    优先级高于内置的前缀白名单：子应用能自己描述它注册的这组工具。
    """

    meta = TOOL_GROUP_META.get(group)
    if meta is not None:
        return meta
    if group.startswith("mcp:"):
        return ("MCP", f"MCP 服务 {group.split(':', 1)[1]} 注册的工具")
    if group == BASIC_GROUP:
        return ("常驻", "平台级交互工具，始终可用")
    if host_group_meta:
        declared_meta = host_group_meta.get(group)
        if declared_meta is not None:
            return declared_meta
    host_meta = _HOST_GROUP_META.get(group)
    if host_meta is not None:
        return host_meta
    return ("页面", "页面宿主注册的工具")


@dataclass(frozen=True)
class ToolGroupLoaderTool:
    """``load_tool_group`` 的工具契约；执行由 tool invoker 拦截，不落业务 handler。"""

    description: str
    input_schema: dict[str, Any]
    name: str = LOAD_TOOL_GROUP_NAME
    kind: str = "builtin"
    side_effect: str = "none"
    group: str = BASIC_GROUP


@dataclass
class ToolGroupState:
    """一次运行内的工具分组与加载状态（不落库，续跑时按清单重建）。

    ``host_groups`` / ``host_group_meta`` 来自宿主连接注册时的声明（工具名 → 组名、
    组名 →（标题，说明））；``eager_groups`` 是声明为「立即加载」的宿主组。三者
    都只影响分组与加载时机，不影响工具语义。
    """

    all_tools: list[Any]
    host_groups: Mapping[str, str] = field(default_factory=dict)
    host_group_meta: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    eager_groups: frozenset[str] = frozenset()
    active: set[str] = field(default_factory=lambda: {BASIC_GROUP})
    # 每次加载递增；模型适配器据此判断是否需要重新 bind_tools。
    version: int = 0

    def __post_init__(self) -> None:
        self._by_group: dict[str, list[str]] = {}
        self._by_name: dict[str, Any] = {}
        for tool in self.all_tools:
            name = str(getattr(tool, "name", "") or "")
            if not name:
                continue
            self._by_name[name] = tool
            self._by_group.setdefault(self._group_of(tool), []).append(name)
        # 立即加载的组在第一次绑定前就进入 active：它们不参与按需加载，
        # 但也必须出现在目录里（目录恒定，见 catalog_text）。
        self.active.update(
            group for group in self._by_group if group in self._eager()
        )

    def _eager(self) -> set[str]:
        """本轮「立即加载」的组名集合：内置常量 + 连接声明。"""

        return EAGER_TOOL_GROUPS | set(self.eager_groups) | {HOST_GROUP}

    def _group_of(self, tool: Any) -> str:
        return tool_group(tool, self.host_groups)

    def _meta_of(self, group: str) -> tuple[str, str]:
        return group_meta(group, self.host_group_meta)

    # ---- 只读视图 ----

    def tools_by_group(self) -> dict[str, list[str]]:
        return {group: list(names) for group, names in self._by_group.items()}

    def pending_groups(self) -> list[str]:
        """尚未加载的分组，按组名排序返回。

        排序是为了让同一批工具在不同入口（REST / WS / 宿主注册顺序不同）下
        生成完全相同的目录文本——目录进系统提示词，逐字不同就会命中不了缓存。
        """

        return sorted(group for group in self._by_group if group not in self.active)

    def is_known_tool(self, name: str) -> bool:
        return name in self._by_name

    def bound_tools(self) -> list[Any]:
        """本轮应绑定的工具：已加载分组内的工具 + 目录工具。"""

        bound = [tool for tool in self.all_tools if self._group_of(tool) in self.active]
        loader = self.loader_tool()
        if loader is not None:
            bound.append(loader)
        return bound

    def loader_tool(self) -> ToolGroupLoaderTool | None:
        """还有未加载分组时给出目录工具，全部加载完就不再占用 schema。"""

        pending = self.pending_groups()
        if not pending:
            return None
        options = "、".join(f"{group}（{self._meta_of(group)[0]}）" for group in pending)
        return ToolGroupLoaderTool(
            description=(
                "按组加载工具定义。平台工具较多，默认只绑定少量常用工具；"
                f"当前还可加载：{options}。"
                "只在你确实需要该组能力时调用，参数 group 必须是上面列出的组名；"
                "加载后的工具在下一轮起可直接调用，且本次会话内保持可用。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "group": {
                        "type": "string",
                        "enum": pending,
                        "description": "要加载的工具组名",
                    }
                },
                "required": ["group"],
                "additionalProperties": False,
            },
        )

    def catalog_text(self) -> str | None:
        """系统提示词里的工具目录：组名 + 一句话 + 组内工具名。

        **列全部组、且与会话内的加载状态无关**：目录进系统提示词，只要文本随
        加载变化，每次加载就会多打一次前缀缓存 miss。代价是模型看不到「哪些组
        已加载」，由 ``load_tool_group`` 的 enum（只含待加载组）和失败文案兜住。
        标记「常驻」的组是立即绑定的组，这个标记只取决于工具清单，同样恒定。
        """

        groups = [group for group in sorted(self._by_group) if group != BASIC_GROUP]
        if not groups:
            return None
        eager = self._eager()
        lines = [
            "工具目录（按组加载）：每组工具默认不预绑定，需要时调用 "
            f"{LOAD_TOOL_GROUP_NAME} 加载对应分组，加载后下一轮即可调用；"
            "标记「常驻」的组已经可用，不必加载。"
        ]
        for group in groups:
            title, summary = self._meta_of(group)
            names = "、".join(sorted(self._by_group[group]))
            marker = "，常驻" if group in eager else ""
            lines.append(f"- {group}（{title}{marker}）：{summary}。工具：{names}")
        return "\n".join(lines)

    # ---- 状态变更 ----

    def restore(self, groups: Iterable[str] | None) -> set[str]:
        """把历史加载过的组恢复成本轮初始加载态，返回真正恢复的组名。

        只恢复「本轮工具清单里确实存在」且「尚未加载」的组；**不递增 version**：
        这是本轮起点，第一次绑定用的就是这份集合，不需要触发重绑。
        """

        restored: set[str] = set()
        for group in groups or ():
            if group in self._by_group and group not in self.active:
                self.active.add(group)
                restored.add(group)
        return restored

    def prefetch(self, message: str) -> set[str]:
        """入口预取：按用户消息把达标的分组并入本轮初始加载态。

        与 :meth:`restore` 一样发生在第一次绑定之前，因此**不递增 version**。
        没猜中（返回空集）时行为与不预取完全一致：模型仍会看到完整目录。
        """

        return self.restore(prefetch_tool_groups(message, self.pending_groups()))

    def activate(self, group: str) -> list[str]:
        """加载一组，返回本次新可见的工具名；未知组或已加载返回空列表。"""

        if group not in self._by_group or group in self.active:
            return []
        self.active.add(group)
        self.version += 1
        return list(self._by_group[group])

    def activate_all(self) -> list[str]:
        """兜底：把全部组一并加载，返回本次新可见的工具名。"""

        added: list[str] = []
        for group in list(self._by_group):
            added.extend(self.activate(group))
        return added

    def handle_loader_call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行 ``load_tool_group``，返回旧链路形状的工具结果字典。"""

        group = str((arguments or {}).get("group", "") or "").strip()
        available = self.pending_groups()
        if not group:
            return {
                "status": "failed",
                "error": {
                    "code": "tool_group_required",
                    "message": "缺少 group 参数，可选值：" + "、".join(available),
                },
            }
        if group in self.active:
            tools = "、".join(sorted(self._by_group.get(group, [])))
            return {
                "status": "failed",
                "error": {
                    "code": "tool_group_loaded",
                    "message": f"工具组 {group} 已加载，可直接调用组内工具：{tools}",
                },
            }
        added = self.activate(group)
        if not added:
            return {
                "status": "failed",
                "error": {
                    "code": "tool_group_unknown",
                    "message": f"工具组 {group} 不存在，可选值：" + "、".join(available),
                },
            }
        return {
            "status": "completed",
            "result": {
                "loaded_group": group,
                "tools": added,
                "note": "该组工具从下一轮起可直接调用。",
            },
            # 结构化记录本次加载，供下一轮/续跑重放加载态（见 restore）。
            "metadata": {LOADED_GROUP_METADATA_KEY: group},
        }


def build_tool_group_state(
    tools: list[Any],
    *,
    enabled: bool = True,
    active_groups: Iterable[str] | None = None,
    host_groups: Mapping[str, str] | None = None,
    host_group_meta: Mapping[str, tuple[str, str]] | None = None,
    eager_groups: Iterable[str] | None = None,
) -> ToolGroupState | None:
    """按需创建分组状态；工具不足以分组（≤1 组）时返回 None，保持旧行为。

    ``active_groups`` 是本会话历史上已加载过的组：把它们恢复成本轮的初始加载
    态，同一个会话的第二轮就不用让模型把同样的组再加载一遍。不在本轮工具清单
    里的组会被忽略——续跑与子运行的工具集合可能比上一轮更小。

    ``host_groups`` / ``host_group_meta`` / ``eager_groups`` 来自宿主连接注册时的
    声明（见 ai-sdk 的 ``registerTools(group=...)`` 与 ``registerToolGroups``）。
    """

    if not enabled:
        return None
    state = ToolGroupState(
        list(tools),
        host_groups=dict(host_groups or {}),
        host_group_meta=dict(host_group_meta or {}),
        eager_groups=frozenset(eager_groups or ()),
    )
    if len(state.tools_by_group()) <= 1:
        return None
    state.restore(active_groups)
    return state
