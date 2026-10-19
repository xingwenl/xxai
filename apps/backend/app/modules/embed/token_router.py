from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.embed.schemas import EmbedTokenResponse
from app.modules.embed.services import issue_configured_agent_token
from app.shared.responses import ApiResponse, success_response

router = APIRouter(tags=["embed"])


@router.get("/agent-token", response_model=ApiResponse[EmbedTokenResponse])
async def get_agent_token(
    external_user_id: str | None = Query(default=None, min_length=1, max_length=255),
    display_name: str | None = Query(default=None, max_length=120),
    origin: str | None = Query(default=None, max_length=500),
    host_tool_names: list[str] = Query(default=[]),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[EmbedTokenResponse]:
    """为本地 Demo 签发短期 SDK token（必须携带后台登录态）。

    Client secret 只从服务端环境变量读取，不接受浏览器提交的 secret。

    ``external_user_id`` 只允许在非生产环境覆盖，用于本地联调时模拟不同终端用户；
    生产环境一律使用当前登录用户 id 作为 token 主体，避免任何人用服务端长期凭据
    为任意终端用户签发 token。非生产环境的覆盖同样要求先通过登录态校验。
    """
    settings = get_settings()
    if external_user_id and settings.app_env != "production":
        subject = external_user_id
    else:
        subject = str(current_user.id)
    token = await issue_configured_agent_token(
        session,
        external_user_id=subject,
        display_name=display_name or current_user.name,
        origin=origin,
        host_tool_names=host_tool_names,
    )
    await session.commit()
    return success_response(data=token, message="agent token issued")
