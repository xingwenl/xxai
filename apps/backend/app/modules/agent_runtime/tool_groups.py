"""按组按需加载工具：只决定「本轮绑定哪些工具」，不改任何工具语义。

设计要点（对应 docs/harness/requests/2026-10-27-tool-groups-lazy-load/spec.md）：

- 分组是**工具侧常量**（内置工具见 ``builtin_tool/groups.py``，宿主工具按名称
  前缀、MCP 按 server_id 推导），与用户意图无关，也不需要分类器参与。
- 常驻的只有两样：系统提示词里的工具目录（``catalog_text``）和
  ``load_tool_group`` 工具本身。
- 加载**单调只增**：一旦加载，本次运行内不再卸载，因此前缀缓存最多每组失效
  一次，而不是每轮失效。
- 兜底必须存在：模型直接调用未加载的工具时，调用器会 ``activate_all()`` 并
  回填可重试的提示，避免出现“工具不在上下文里、模型永远没有机会”的死局。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.builtin_tool.groups import BASIC_GROUP, TOOL_GROUP_META

# 按需加载工具名：与 load_skill 同一套「常驻目录 + 按需加载」范式。
LOAD_TOOL_GROUP_NAME = "load_tool_group"

# 宿主工具名前缀无法识别时的兜底组名。
HOST_GROUP = "host"

# 兜底提示：模型调用了未加载的工具时返回，明确要求它重试同一次调用。
RETRY_HINT = "工具组已全部加载，请立即重试刚才的工具调用，不需要再调用 {loader}。"


def tool_group(tool: Any) -> str:
    """判定工具所属分组：优先工具自身声明，其次按来源形态推导。

    内置业务工具带 ``group`` 字段；MCP 工具带 ``server_id``；技能脚本/指令工具
    带 ``kind``；宿主（页面）工具只有名称，按「子应用_动作」的前缀约定分组。
    """

    declared = getattr(tool, "group", None)
    if isinstance(declared, str) and declared:
        return declared
    server_id = getattr(tool, "server_id", None)
    if server_id is not None:
        return f"mcp:{server_id}"
    kind = str(getattr(tool, "kind", "") or "")
    if kind.startswith("skill"):
        return "skill"
    return _host_group(str(getattr(tool, "name", "") or ""))


def _host_group(name: str) -> str:
    """宿主工具按名称首段分组：``ledger_add_entry`` → ``ledger``。"""

    head = name.split("_", 1)[0].split(".", 1)[0]
    if not head or head == name:
        return HOST_GROUP
    return head


def group_meta(group: str) -> tuple[str, str]:
    """分组展示信息：返回（标题，一句话说明），未知组按名称原样展示。"""

    meta = TOOL_GROUP_META.get(group)
    if meta is not None:
        return meta
    if group.startswith("mcp:"):
        return ("MCP", f"MCP 服务 {group.split(':', 1)[1]} 注册的工具")
    if group == BASIC_GROUP:
        return ("常驻", "平台级交互工具，始终可用")
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
    """一次运行内的工具分组与加载状态（不落库，续跑时按清单重建）。"""

    all_tools: list[Any]
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
            self._by_group.setdefault(tool_group(tool), []).append(name)

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

        bound = [tool for tool in self.all_tools if tool_group(tool) in self.active]
        loader = self.loader_tool()
        if loader is not None:
            bound.append(loader)
        return bound

    def loader_tool(self) -> ToolGroupLoaderTool | None:
        """还有未加载分组时给出目录工具，全部加载完就不再占用 schema。"""

        pending = self.pending_groups()
        if not pending:
            return None
        options = "、".join(f"{group}（{group_meta(group)[0]}）" for group in pending)
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
        """系统提示词里的工具目录：组名 + 一句话 + 组内工具名。"""

        pending = self.pending_groups()
        if not pending:
            return None
        lines = [
            "工具目录（按组加载）：默认只绑定了部分工具，其他能力需要先调用 "
            f"{LOAD_TOOL_GROUP_NAME} 加载对应分组，加载后下一轮即可调用。"
        ]
        for group in pending:
            title, summary = group_meta(group)
            names = "、".join(sorted(self._by_group[group]))
            lines.append(f"- {group}（{title}）：{summary}。工具：{names}")
        return "\n".join(lines)

    # ---- 状态变更 ----

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
        added = self.activate(group)
        if not added:
            return {
                "status": "failed",
                "error": {
                    "code": "tool_group_unknown",
                    "message": f"工具组 {group} 不存在或已加载，可选值："
                    + "、".join(available),
                },
            }
        return {
            "status": "completed",
            "result": {
                "loaded_group": group,
                "tools": added,
                "note": "该组工具从下一轮起可直接调用。",
            },
        }


def build_tool_group_state(
    tools: list[Any], *, enabled: bool = True
) -> ToolGroupState | None:
    """按需创建分组状态；工具不足以分组（≤1 组）时返回 None，保持旧行为。"""

    if not enabled:
        return None
    state = ToolGroupState(list(tools))
    if len(state.tools_by_group()) <= 1:
        return None
    return state
