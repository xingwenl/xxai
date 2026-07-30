from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.mcp.repositories import McpRepository
from app.modules.mcp.runtime import RepositoryMcpExecutor, StreamableHttpMcpClient
from app.modules.mcp.schemas import (
    AgentMcpBind,
    ConfirmationResolveRequest,
    McpAuditRead,
    McpServerCreate,
    McpServerListData,
    McpServerRead,
    McpServerUpdate,
    AgentMcpServerRead,
    McpToolPolicyUpdate,
    McpToolRead,
    ToolInvocationOutcome,
    ToolInvokeRequest,
)
from app.modules.mcp.services import (
    create_mcp_server,
    delete_mcp_server,
    invoke_tool,
    resolve_tool_confirmation,
    sync_mcp_tools,
    unbind_mcp_server,
    update_mcp_server,
)
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.pagination import PaginationParams, pagination_dependency
from app.shared.responses import ApiResponse, success_response

router = APIRouter(prefix="/platforms/{platform_id}", tags=["mcp"])


async def _require_admin(platform_id: int, user_id: int, session: AsyncSession):
    if (
        await PlatformRepository(session).get_by_id_for_user(platform_id, user_id)
        is None
    ):
        raise NotFoundException("platform not found")


def _server_read(server) -> McpServerRead:
    return McpServerRead.model_validate(
        {**server.__dict__, "has_auth_headers": bool(server.auth_headers_encrypted)}
    )


@router.post(
    "/mcp-servers",
    response_model=ApiResponse[McpServerRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_server_endpoint(
    platform_id: int,
    payload: McpServerCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    server = await create_mcp_server(McpRepository(session), platform_id, payload)
    return success_response(data=_server_read(server), message="MCP server created")


@router.get("/mcp-servers", response_model=ApiResponse[McpServerListData])
async def list_servers_endpoint(
    platform_id: int,
    params: PaginationParams = Depends(pagination_dependency),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    page = await McpRepository(session).list_servers(platform_id, params)
    return success_response(
        data=McpServerListData.model_validate(page.model_dump()),
        message="MCP servers listed",
    )


@router.patch("/mcp-servers/{server_id}", response_model=ApiResponse[McpServerRead])
async def update_server_endpoint(
    platform_id: int,
    server_id: int,
    payload: McpServerUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    server = await update_mcp_server(
        McpRepository(session), platform_id, server_id, payload
    )
    return success_response(data=_server_read(server), message="MCP server updated")


@router.delete("/mcp-servers/{server_id}", response_model=ApiResponse[None])
async def delete_server_endpoint(
    platform_id: int,
    server_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    await delete_mcp_server(McpRepository(session), platform_id, server_id)
    return success_response(message="MCP server deleted")


@router.post(
    "/mcp-servers/{server_id}/sync", response_model=ApiResponse[list[McpToolRead]]
)
async def sync_tools_endpoint(
    platform_id: int,
    server_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = McpRepository(session)
    server = await repo.get_server(server_id, platform_id)
    if server is None:
        raise NotFoundException("MCP server not found")
    tools = await sync_mcp_tools(repo, StreamableHttpMcpClient(), server)
    return success_response(data=[McpToolRead.model_validate(tool) for tool in tools])


@router.get(
    "/mcp-servers/{server_id}/tools", response_model=ApiResponse[list[McpToolRead]]
)
async def list_tools_endpoint(
    platform_id: int,
    server_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = McpRepository(session)
    if await repo.get_server(server_id, platform_id) is None:
        raise NotFoundException("MCP server not found")
    return success_response(
        data=[
            McpToolRead.model_validate(tool)
            for tool in await repo.list_tools(server_id, platform_id)
        ],
        message="MCP tools listed",
    )


@router.patch("/mcp-tools/{tool_id}", response_model=ApiResponse[McpToolRead])
async def update_tool_policy_endpoint(
    platform_id: int,
    tool_id: int,
    payload: McpToolPolicyUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    tool = await McpRepository(session).update_tool_policy(
        tool_id, platform_id, payload
    )
    if tool is None:
        raise NotFoundException("MCP tool not found")
    return success_response(
        data=McpToolRead.model_validate(tool), message="tool policy updated"
    )


@router.put("/agents/{agent_id}/mcp-servers", response_model=ApiResponse[dict])
async def bind_server_endpoint(
    platform_id: int,
    agent_id: int,
    payload: AgentMcpBind,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    binding = await McpRepository(session).bind_server(
        platform_id, agent_id, payload.server_id
    )
    if binding is None:
        raise NotFoundException("agent or MCP server not found")
    return success_response(
        data={"agent_id": agent_id, "server_id": payload.server_id},
        message="MCP server bound",
    )


@router.get(
    "/agents/{agent_id}/mcp-servers",
    response_model=ApiResponse[list[AgentMcpServerRead]],
)
async def list_agent_servers_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    bindings = await McpRepository(session).list_server_bindings(platform_id, agent_id)
    return success_response(
        data=[AgentMcpServerRead.model_validate(item) for item in bindings],
        message="agent MCP servers listed",
    )


@router.delete(
    "/agents/{agent_id}/mcp-servers/{server_id}", response_model=ApiResponse[None]
)
async def unbind_server_endpoint(
    platform_id: int,
    agent_id: int,
    server_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    await unbind_mcp_server(McpRepository(session), platform_id, agent_id, server_id)
    return success_response(message="MCP server unbound")


@router.post(
    "/agents/{agent_id}/mcp-tools/invoke",
    response_model=ApiResponse[ToolInvocationOutcome],
)
async def invoke_tool_endpoint(
    platform_id: int,
    agent_id: int,
    payload: ToolInvokeRequest,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = McpRepository(session)
    outcome = await invoke_tool(
        repo,
        RepositoryMcpExecutor(repo),
        platform_id=platform_id,
        agent_id=agent_id,
        user_id=current_user.id,
        server_id=payload.server_id,
        tool_name=payload.tool_name,
        arguments=payload.arguments,
    )
    return success_response(data=outcome)


@router.post(
    "/mcp-confirmations/{confirmation_id}/resolve",
    response_model=ApiResponse[ToolInvocationOutcome],
)
async def resolve_confirmation_endpoint(
    platform_id: int,
    confirmation_id: int,
    payload: ConfirmationResolveRequest,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = McpRepository(session)
    outcome = await resolve_tool_confirmation(
        repo,
        RepositoryMcpExecutor(repo),
        confirmation_id=confirmation_id,
        platform_id=platform_id,
        user_id=current_user.id,
        approved=payload.approved,
    )
    return success_response(data=outcome)


@router.get("/mcp-audits", response_model=ApiResponse[list[McpAuditRead]])
async def list_audits_endpoint(
    platform_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    audits = await McpRepository(session).list_audits(platform_id, limit)
    return success_response(
        data=[McpAuditRead.model_validate(audit) for audit in audits]
    )
