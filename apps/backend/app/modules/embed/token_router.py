from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.embed.schemas import EmbedTokenResponse
from app.modules.embed.services import issue_configured_agent_token
from app.shared.responses import ApiResponse, success_response

router = APIRouter(tags=["embed"])


@router.get("/agent-token", response_model=ApiResponse[EmbedTokenResponse])
async def get_agent_token(
    external_user_id: str = Query(min_length=1, max_length=255),
    display_name: str | None = Query(default=None, max_length=120),
    origin: str | None = Query(default=None, max_length=500),
    host_tool_names: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[EmbedTokenResponse]:
    """为本地 Demo/业务后端代理签发短期 SDK token。

    Client secret 只从服务端环境变量读取，不接受浏览器提交的 secret。
    生产环境应将 external_user_id 绑定到业务登录态后再开放此代理接口。
    """
    token = await issue_configured_agent_token(
        session,
        external_user_id=external_user_id,
        display_name=display_name,
        origin=origin,
        host_tool_names=host_tool_names,
    )
    await session.commit()
    return success_response(data=token, message="agent token issued")
