"""业务工具框架：业务上下文、注册表与装饰器。

职责边界：业务工具只做来源解析、鉴权、持久化、Agent 模型绑定解析与结果包装；
能力实现一律委托给基本工具。

副作用声明：业务工具可以用 ``depends_on`` 包装能力原子，因此**自身声明值可能
低于它实际造成的后果**（例如包装 ``image_gen.generate`` 却声明 ``none``）。
:func:`effective_side_effect` 取「声明值与各依赖声明值的最大者」，审批闸口只认
这个生效值；:func:`validate_business_tool_dependencies` 在启动期把低报直接报错。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.modules.tools.side_effects import (
    SideEffect,
    max_side_effect,
    normalize_side_effect,
    side_effect_rank,
)


class BusinessToolError(Exception):
    """业务工具统一异常：code 为 LLM 稳定错误码，status_code 可选透传。"""

    def __init__(self, code: str, message: str = "", *, status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class BusinessToolContext:
    """基本工具不该知道的东西都放这里。"""

    platform_id: int
    agent_id: int
    conversation_id: int
    user_id: int | None = None
    platform_end_user_id: int | None = None
    # 当前这次运行在 agent_loop_runs 里的 ID：委派类工具据此把子运行挂到父运行下。
    # 由调用方经 loop_run_id_provider 注入，非委派场景为 None。
    loop_run_id: int | None = None
    session: Any | None = None  # DB 会话：查 asset / 模型绑定
    asset_repo: Any | None = None
    # 店铺运营平台（hua8）会话：由 shop-agent 会话接口注入，工具用它调店铺系统接口。
    shop_token: str | None = None
    shop_user_id: str | None = None
    # 本次运行的审批裁决器：委派类工具把它传给子运行，让子运行继承父的审批策略。
    # 交互式运行传 None（没有可问的人），子运行据此走「无确认通道」拒绝分支。
    confirmation_decider: Any | None = None


@dataclass(frozen=True)
class BusinessTool:
    name: str  # LLM 看到的工具名
    description: str
    input_schema: dict[str, Any]  # LLM 看到的输入契约（业务化输入）
    handler: Callable[[dict[str, Any], BusinessToolContext], Awaitable[dict[str, Any]]]
    depends_on: tuple[str, ...] = ()  # 依赖的基本工具注册键
    # 自身声明的副作用；生效值请用 effective_side_effect()（会被依赖抬高）。
    side_effect: str = "none"


BUSINESS_TOOL_REGISTRY: dict[str, BusinessTool] = {}


def business_tool(
    name: str,
    *,
    description: str,
    input_schema: dict[str, Any],
    depends_on: tuple[str, ...] = (),
    side_effect: str = "none",
):
    """装饰器：定义与 handler 写在同一个文件，导入即注册。"""

    if name in BUSINESS_TOOL_REGISTRY:
        raise ValueError(f"business tool {name}: already registered")
    normalized_side_effect = normalize_side_effect(
        side_effect, where=f"business tool {name}"
    )

    def decorator(handler):
        BUSINESS_TOOL_REGISTRY[name] = BusinessTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            depends_on=depends_on,
            side_effect=normalized_side_effect,
        )
        return handler

    return decorator


def effective_side_effect(tool: BusinessTool, basic_resolver) -> SideEffect:
    """业务工具的生效副作用 = 自身声明值与各依赖声明值中的最保守者。

    取最大值的理由：包装层可能低估后果（只声明 ``none`` 却调用了会写数据的
    能力原子）。审批闸口必须看到真实后果，否则又会出现「声明是 none、实际在写库」。
    """

    candidates: list[object] = [tool.side_effect]
    for dependency in tool.depends_on:
        basic = basic_resolver(dependency)
        if basic is not None:
            candidates.append(getattr(basic, "side_effect", None))
    return max_side_effect(*candidates)


def validate_business_tool_dependencies(basic_resolver) -> list[str]:
    """启动校验：返回问题列表（空列表表示全部合法）。

    校验两件事——声明的依赖必须已注册；声明的副作用不得低于依赖暴露的最大值
    （低报会被 :func:`effective_side_effect` 抬高，但那是兜底，启动期就该报错）。
    """

    problems: list[str] = []
    for tool in BUSINESS_TOOL_REGISTRY.values():
        declared = normalize_side_effect(tool.side_effect, where=f"business tool {tool.name}")
        dependency_max: SideEffect = "none"
        for dependency in tool.depends_on:
            basic = basic_resolver(dependency)
            if basic is None:
                problems.append(f"{tool.name}: dependency {dependency} is not registered")
                continue
            dependency_max = max_side_effect(
                dependency_max, getattr(basic, "side_effect", None)
            )
        if side_effect_rank(declared) < side_effect_rank(dependency_max):
            problems.append(
                f"{tool.name}: side_effect {declared!r} is lower than its "
                f"dependency maximum {dependency_max!r}"
            )
    return problems
