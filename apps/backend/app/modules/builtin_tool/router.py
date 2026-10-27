from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.agent.repositories import AgentRepository
from app.modules.builtin_tool.registry import get_builtin_tool, list_builtin_tools
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.builtin_tool.schemas import (
    AgentBuiltinToolRead,
    AgentBuiltinToolUpdate,
    BuiltinToolCatalogRead,
    ToolGroupCatalogRead,
    ToolGroupRead,
)
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(prefix="/platforms/{platform_id}", tags=["builtin-tools"])


async def _require_admin(platform_id: int, user_id: int, session: AsyncSession):
    if (
        await PlatformRepository(session).get_by_id_for_user(platform_id, user_id)
        is None
    ):
        raise NotFoundException("platform not found")


def _catalog_read(tool) -> BuiltinToolCatalogRead:
    return BuiltinToolCatalogRead(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        side_effect=tool.side_effect,
    )


def _group_reads(
    groups: dict[str, list[str]], *, eager_groups: set[str]
) -> list[ToolGroupRead]:
    """把「组名 → 工具名」渲染成带展示信息的清单。

    排序规则：``basic``（常驻交互）最先、``host``（兜底宿主组）最后，中间 eager 组
    在按需组之前，同级按标题排序——让页面从上到下读起来像「始终可用 → 提前绑定 →
    需要时才加载」。
    """
    # 延迟导入：分组判定函数住在 agent_runtime，而该包在导入期会拉上
    # conversation 适配器，模块顶层互引会成环。
    from app.modules.agent_runtime.tool_groups import (
        HOST_GROUP,
        group_meta,
    )
    from app.modules.builtin_tool.groups import BASIC_GROUP

    def _rank(group: str) -> int:
        if group == BASIC_GROUP:
            return 0
        if group == HOST_GROUP:
            return 3
        return 1 if group in eager_groups else 2

    reads = []
    for group, names in groups.items():
        title, description = group_meta(group)
        reads.append(
            ToolGroupRead(
                group=group,
                title=title,
                description=description,
                eager=group in eager_groups,
                tool_names=sorted(names),
            )
        )
    return sorted(reads, key=lambda item: (_rank(item.group), item.title))


async def _tool_group_catalog(platform_id: int, session) -> ToolGroupCatalogRead:
    """组装工具组目录：内置组来自代码常量，宿主组来自平台的工具策略。"""
    from app.modules.agent_runtime.tool_groups import (
        HOST_GROUP,
        tool_group,
    )
    from app.modules.builtin_tool.groups import BASIC_GROUP, EAGER_TOOL_GROUPS
    from app.modules.host_tool.repositories import HostToolRepository

    builtin_groups: dict[str, list[str]] = {}
    for tool in list_builtin_tools():
        builtin_groups.setdefault(tool.group, []).append(tool.name)

    host_groups: dict[str, list[str]] = {}
    for policy in await HostToolRepository(session).list_policies(platform_id):
        host_groups.setdefault(tool_group(policy), []).append(policy.name)

    # basic 组按构造始终绑定、宿主兜底组（``host``）的成员无法被定向加载，
    # 两者在展示上都算「常驻」；其余组默认异步加载，除非显式声明 eager。
    host_eager = set(EAGER_TOOL_GROUPS) | {HOST_GROUP}
    return ToolGroupCatalogRead(
        builtin=_group_reads(
            builtin_groups, eager_groups=set(EAGER_TOOL_GROUPS) | {BASIC_GROUP}
        ),
        host=_group_reads(host_groups, eager_groups=host_eager),
    )


@router.get(
    "/tool-groups",
    response_model=ApiResponse[ToolGroupCatalogRead],
    tags=["builtin-tools"],
)
async def list_tool_groups_endpoint(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    """只读工具组目录：给管理台按组展示用，组关系不在此处可写。"""
    await _require_admin(platform_id, current_user.id, session)
    return success_response(data=await _tool_group_catalog(platform_id, session))


@router.get("/builtin-tools", response_model=ApiResponse[list[BuiltinToolCatalogRead]])
async def list_catalog_endpoint(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    return success_response(data=[_catalog_read(tool) for tool in list_builtin_tools()])


@router.get(
    "/agents/{agent_id}/builtin-tools",
    response_model=ApiResponse[list[AgentBuiltinToolRead]],
)
async def list_agent_tools_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    if await AgentRepository(session).get_agent(agent_id, platform_id) is None:
        raise NotFoundException("agent not found")
    bindings = {
        item.tool_name: item
        for item in await BuiltinToolRepository(session).list_bindings(
            platform_id, agent_id
        )
    }
    return success_response(
        data=[
            AgentBuiltinToolRead(
                **_catalog_read(tool).model_dump(),
                is_enabled=bool(
                    bindings.get(tool.name) and bindings[tool.name].is_enabled
                ),
            )
            for tool in list_builtin_tools()
        ]
    )


@router.put(
    "/agents/{agent_id}/builtin-tools/{tool_name}",
    response_model=ApiResponse[AgentBuiltinToolRead],
)
async def update_agent_tool_endpoint(
    platform_id: int,
    agent_id: int,
    tool_name: str,
    payload: AgentBuiltinToolUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    tool = get_builtin_tool(tool_name)
    binding = await BuiltinToolRepository(session).set_binding(
        platform_id, agent_id, tool_name, is_enabled=payload.is_enabled
    )
    if tool is None or binding is None:
        raise NotFoundException("builtin tool or agent not found")
    return success_response(
        data=AgentBuiltinToolRead(
            **_catalog_read(tool).model_dump(), is_enabled=binding.is_enabled
        )
    )
