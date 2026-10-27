"""工具组预取与加载的离线回放、聚合与报告渲染（只读，不参与运行期）。

为什么用「回放」而不是「埋点」
------------------------------
要回答的问题只有四个：预取命中率、``load_tool_group`` 触发率、
``tool_not_loaded`` 兜底率、每轮实际绑定的工具 schema 体积。

其中三个事实已经落库：``load_tool_group`` 的组名在步骤元数据里，工具调用名在
``AgentLoopStep.tool_name`` 上，本轮的用户消息在 ``ConversationMessage.content``
上。剩下的两个派生量——预取结果、某次调用时该组是否已加载——都是**确定性纯
函数**（:func:`prefetch_tool_groups` 只看用户消息与待加载组；加载态只看之前的
``load_tool_group`` 序列）。所以用同一条用户消息重放一遍，得到的结论与线上
逐字一致，不必新增埋点，也不会与实现漂移。

代价是回放假设「当时的工具清单与现在一致」：工具增删后旧运行的绑定体积会按新
清单重算。统计用于横向对比（改前/改后、周与周），不适合当账单。
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from app.modules.agent_runtime.tool_groups import (
    LOAD_TOOL_GROUP_NAME,
    ToolGroupState,
    build_tool_group_state,
)

# 字符 → token 的折算。19 个内置工具实测 18,198 字符 ≈ 9,114 token，约 2.0
# 字符/token；这里只用于同一个仓库内前后对比，不用于预算判断。
CHARS_PER_TOKEN = 2.0

# 回放序列里的两种动作：加载一组、调用一个工具。
STEP_LOAD = "load"
STEP_CALL = "call"


def tool_schema_chars(tool: Any) -> int:
    """按 ``bind_tools`` 的载荷形状估算单个工具的 schema 字符数。

    生产链路上工具被转成 ``{"type": "function", "function": {...}}`` 后交给
    provider（见 ``agent_runtime/langchain_adapter.py`` 的 ``_bind_tools``），
    这里保持同一形状，保证加总后能与线上体积对话。
    """

    payload = {
        "type": "function",
        "function": {
            "name": str(getattr(tool, "name", "") or ""),
            "description": str(getattr(tool, "description", "") or ""),
            "parameters": getattr(tool, "input_schema", None) or {},
        },
    }
    return len(json.dumps(payload, ensure_ascii=False))


def _bound_chars(state: ToolGroupState) -> int:
    return sum(tool_schema_chars(tool) for tool in state.bound_tools())


def observe_run(
    tools: Sequence[Any],
    *,
    user_message: str = "",
    steps: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """回放一次运行，返回该次的观测值。

    ``steps`` 是按落库顺序排好的动作序列：``(STEP_LOAD, 组名)`` 表示模型调用了
    ``load_tool_group``，``(STEP_CALL, 工具名)`` 表示一次业务工具调用。
    """

    tool_list = list(tools)
    observation: dict[str, Any] = {
        "grouped": False,
        "tool_calls": 0,
        "external_calls": 0,
        "load_calls": 0,
        "prefetched_groups": [],
        "loaded_groups": [],
        "used_groups": [],
        "unbound_calls": 0,
        "unbound_tools": [],
        "wasted_loads": 0,
        "groups_bound_start": 0,
        "bound_chars_start": 0,
        "bound_chars_max": 0,
    }

    state = build_tool_group_state(tool_list)
    if state is None:
        # 工具不足以分组：线上全量绑定，没有预取与加载可言。
        chars = sum(tool_schema_chars(tool) for tool in tool_list)
        observation.update(
            groups_bound_start=1, bound_chars_start=chars, bound_chars_max=chars
        )
        for kind, value in steps:
            if kind == STEP_CALL:
                observation["tool_calls"] += 1
        return observation

    group_of_name = {
        name: group
        for group, names in state.tools_by_group().items()
        for name in names
    }
    observation["grouped"] = True
    observation["prefetched_groups"] = sorted(state.prefetch(user_message or ""))
    observation["groups_bound_start"] = len(state.active)
    observation["bound_chars_start"] = _bound_chars(state)
    observation["bound_chars_max"] = observation["bound_chars_start"]

    for kind, value in steps:
        if kind == STEP_LOAD:
            observation["load_calls"] += 1
            if state.activate(value):
                observation["loaded_groups"].append(value)
                observation["bound_chars_max"] = max(
                    observation["bound_chars_max"], _bound_chars(state)
                )
        elif kind == STEP_CALL:
            observation["tool_calls"] += 1
            group = group_of_name.get(value)
            if group is None:
                # 宿主工具、MCP 工具不在这份回放清单里：无法判断所属组是否已
                # 加载，单独计数，避免把它们误算成「未加载导致兜底」。
                observation["external_calls"] += 1
                continue
            observation["used_groups"].append(group)
            if group not in state.active:
                observation["unbound_calls"] += 1
                observation["unbound_tools"].append(value)

    observation["wasted_loads"] = sum(
        1 for group in observation["loaded_groups"] if group not in observation["used_groups"]
    )
    return observation


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def summarize(observations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """把逐次运行的观测聚合成一张可对比的表。"""

    runs = len(observations)
    if runs == 0:
        return {
            "runs": 0,
            "tool_calls": 0,
            "avg_tool_calls": 0.0,
            "load_calls": 0,
            "load_runs": 0,
            "load_run_rate": 0.0,
            "avg_load_calls": 0.0,
            "wasted_loads": 0,
            "fallback_runs": 0,
            "fallback_rate": 0.0,
            "prefetch_runs": 0,
            "prefetch_rate": 0.0,
            "prefetch_useful_runs": 0,
            "prefetch_useful_rate": 0.0,
            "avg_bound_chars_start": 0.0,
            "avg_bound_chars_max": 0.0,
            "avg_bound_tokens_start": 0.0,
            "avg_bound_tokens_max": 0.0,
            "top_loaded_groups": [],
            "top_used_groups": [],
        }

    tool_calls = sum(o["tool_calls"] for o in observations)
    load_calls = sum(o["load_calls"] for o in observations)
    load_runs = sum(1 for o in observations if o["load_calls"])
    fallback_runs = sum(1 for o in observations if o["unbound_calls"])
    prefetch_runs = sum(1 for o in observations if o["prefetched_groups"])
    # 「预取有效」＝预取的组里至少有一个组内工具真的被调用；其余算白预取。
    prefetch_useful_runs = sum(
        1
        for o in observations
        if set(o["prefetched_groups"]) & set(o["used_groups"])
    )
    bound_start = [o["bound_chars_start"] for o in observations]
    bound_max = [o["bound_chars_max"] for o in observations]
    loaded_counter: Counter[str] = Counter()
    used_counter: Counter[str] = Counter()
    for observation in observations:
        loaded_counter.update(observation["loaded_groups"])
        used_counter.update(observation["used_groups"])

    return {
        "runs": runs,
        "tool_calls": tool_calls,
        "avg_tool_calls": _rate(tool_calls, runs),
        "load_calls": load_calls,
        "load_runs": load_runs,
        "load_run_rate": _rate(load_runs, runs),
        "avg_load_calls": _rate(load_calls, runs),
        "wasted_loads": sum(o["wasted_loads"] for o in observations),
        "fallback_runs": fallback_runs,
        "fallback_rate": _rate(fallback_runs, runs),
        "prefetch_runs": prefetch_runs,
        "prefetch_rate": _rate(prefetch_runs, runs),
        "prefetch_useful_runs": prefetch_useful_runs,
        "prefetch_useful_rate": _rate(prefetch_useful_runs, prefetch_runs),
        "avg_bound_chars_start": _rate(sum(bound_start), runs),
        "avg_bound_chars_max": _rate(sum(bound_max), runs),
        "avg_bound_tokens_start": _rate(int(sum(bound_start) / CHARS_PER_TOKEN), runs),
        "avg_bound_tokens_max": _rate(int(sum(bound_max) / CHARS_PER_TOKEN), runs),
        "top_loaded_groups": loaded_counter.most_common(10),
        "top_used_groups": used_counter.most_common(10),
    }


def render_markdown(stats: dict[str, Any]) -> str:
    """把聚合结果渲染成一段可直接贴进 issue/评审的 markdown。"""

    lines = [
        "# 工具组基线（离线回放）",
        "",
        f"- 运行数：{stats['runs']}",
        f"- 工具调用总数：{stats['tool_calls']}（平均 {stats['avg_tool_calls']}/次运行）",
        f"- {LOAD_TOOL_GROUP_NAME} 调用：{stats['load_calls']} 次，"
        f"触发率 {stats['load_run_rate'] * 100:.1f}%（{stats['load_runs']}/{stats['runs']} 次运行），"
        f"平均 {stats['avg_load_calls']} 次/运行；其中白加载 {stats['wasted_loads']} 组",
        f"- 未加载即调用（线上会触发自动兜底）：{stats['fallback_runs']} 次运行，"
        f"占比 {stats['fallback_rate'] * 100:.1f}%",
        f"- 首轮预取：命中 {stats['prefetch_runs']} 次运行"
        f"（{stats['prefetch_rate'] * 100:.1f}%），"
        f"其中预取组真被用上 {stats['prefetch_useful_runs']} 次"
        f"（有效率 {stats['prefetch_useful_rate'] * 100:.1f}%）",
        "",
        "| 指标 | 首轮绑定 | 运行内最大绑定 |",
        "| --- | --- | --- |",
        f"| 平均字符数 | {stats['avg_bound_chars_start']:.0f} | {stats['avg_bound_chars_max']:.0f} |",
        f"| 约合 token | {stats['avg_bound_tokens_start']:.0f} | {stats['avg_bound_tokens_max']:.0f} |",
    ]
    if stats["top_loaded_groups"]:
        lines += ["", "**最常被显式加载的组**：" + "、".join(
            f"{group}（{count}）" for group, count in stats["top_loaded_groups"]
        )]
    if stats["top_used_groups"]:
        lines += ["", "**最常被调用的组**：" + "、".join(
            f"{group}（{count}）" for group, count in stats["top_used_groups"]
        )]
    return "\n".join(lines)
