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
