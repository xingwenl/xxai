"""工具副作用类型的唯一词汇表与保守度排序。

为什么单独一个模块：副作用声明在仓里曾有三套互不兼容的写法——
MCP 与宿主工具用规范五值（``app/modules/mcp/schemas.py``、
``app/modules/host_tool/schemas.py``），基本工具用 ``{"none", "create"}``，
业务工具则完全没有这个字段。三套写法让「这个工具到底会不会写数据」
在不同层得到不同答案，审批闸口因此形同虚设。

本模块给出唯一来源：所有声明与读取都经过这里，声明期非法值快速失败，
运行期读取永不抛异常（读侧用 :func:`coerce_side_effect`）。
"""

from __future__ import annotations

from typing import Literal

# 规范五值：与 MCP / 宿主工具两侧既有声明一致，前端也已按这五值渲染
# （``apps/front/src/api/mcp-servers.ts`` 的 side_effect 联合类型）。
SideEffect = Literal["none", "navigation", "write", "financial", "external"]

SIDE_EFFECTS: tuple[SideEffect, ...] = (
    "none",
    "navigation",
    "write",
    "financial",
    "external",
)

# 历史别名：能力层早期用 "create" 表示「产生新数据」，语义等价于 "write"。
SIDE_EFFECT_ALIASES: dict[str, SideEffect] = {"create": "write"}

# 保守度全序：出现分歧时取最靠后（最保守）的一方。
# financial 排最后，因为无人值守策略把它硬编码为「一律不自动批准」
# （``app/modules/tasks/unattended.py`` 的 NEVER_AUTO_APPROVE_SIDE_EFFECTS）：
# 一旦某条依赖链上出现 financial，整条链都不该被自动批准。
SIDE_EFFECT_ORDER: tuple[SideEffect, ...] = (
    "none",
    "navigation",
    "write",
    "external",
    "financial",
)

_ORDER_INDEX: dict[str, int] = {
    value: index for index, value in enumerate(SIDE_EFFECT_ORDER)
}

# 未知取值在运行期的保守回落：按「需要确认」处理，绝不静默降级成 none
# （静默降级成 none 等于无声放行一个来源不明的工具）。
UNKNOWN_SIDE_EFFECT: SideEffect = "external"


class SideEffectError(ValueError):
    """副作用取值非法。声明期抛出，让错误在启动时就暴露。"""


def normalize_side_effect(value: object, *, where: str = "") -> SideEffect:
    """声明期归一：别名转正、空值视为 none、未知值抛错。

    ``where`` 用于拼出可定位的报错前缀（例如装饰器把工具名传进来）。
    """

    raw = str(value or "").strip().lower()
    if not raw:
        return "none"
    raw = SIDE_EFFECT_ALIASES.get(raw, raw)  # type: ignore[assignment]
    if raw not in _ORDER_INDEX:
        prefix = f"{where}: " if where else ""
        raise SideEffectError(
            f"{prefix}invalid side_effect {value!r}, expected one of {SIDE_EFFECT_ORDER}"
        )
    return raw  # type: ignore[return-value]


def coerce_side_effect(value: object) -> SideEffect:
    """运行期读取：永不抛异常。

    空值视为 none；别名转正；未知值按 :data:`UNKNOWN_SIDE_EFFECT` 保守处理，
    这样即使某个工具来源的声明不合规，也不会被当作「无副作用」直接执行。
    """

    raw = str(value or "").strip().lower()
    if not raw:
        return "none"
    raw = SIDE_EFFECT_ALIASES.get(raw, raw)  # type: ignore[assignment]
    if raw not in _ORDER_INDEX:
        return UNKNOWN_SIDE_EFFECT
    return raw  # type: ignore[return-value]


def max_side_effect(*values: object) -> SideEffect:
    """取若干声明里最保守的一个；全为空时返回 none。"""

    normalized = [coerce_side_effect(value) for value in values if str(value or "").strip()]
    if not normalized:
        return "none"
    return max(normalized, key=lambda item: _ORDER_INDEX[item])


def side_effect_rank(value: object) -> int:
    """返回保守度排名，数值越大越保守（用于声明一致性的比较）。"""

    return _ORDER_INDEX[coerce_side_effect(value)]
