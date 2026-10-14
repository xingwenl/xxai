"""后台会话记录（平台级只读接口）。

与 `conversation/router.py` 的聊天入口不同，这里的调用方是后台管理员，作用域是
整个平台：可以查阅本平台下所有会话主体的会话、消息与用量。隔离与鉴权全部落在
`_require_admin`（平台成员关系），非成员一律 404 而不是 403——沿用本仓库既有
后台接口「不泄露他平台资源是否存在」的口径，见 ADR 0003。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.conversation.schemas import (
    ConsoleConversationDetail,
    ConsoleConversationPage,
    ConversationPrincipalPage,
)
from app.modules.conversation.services import (
    delete_console_conversation,
    get_console_conversation,
    list_console_conversation_messages,
    list_console_conversation_principals,
    list_console_conversations,
)
from app.modules.embed.schemas import ConversationMessageRead
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import BadRequestException, NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(
    prefix="/platforms/{platform_id}",
    tags=["conversation"],
)


async def _require_admin(
    platform_id: int,
    user_id: int,
    session: AsyncSession,
) -> None:
    """平台管理员校验：平台不存在或当前用户不是其成员时统一 404。"""
    if (
        await PlatformRepository(session).get_by_id_for_user(platform_id, user_id)
        is None
    ):
        raise NotFoundException("platform not found")


def _validate_dates(start_date: date | None, end_date: date | None) -> None:
    """只给一端日期时按开区间处理，两端都给了才需要检查先后。"""
    if start_date is not None and end_date is not None and start_date > end_date:
        raise BadRequestException("start_date must be before or equal to end_date")


@router.get(
    "/conversation-principals",
    response_model=ApiResponse[ConversationPrincipalPage],
)
async def list_conversation_principals_endpoint(
    platform_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal_type: str | None = Query(default=None, pattern="^(user|end_user)$"),
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ConversationPrincipalPage]:
    """第一层：本平台内「有会话」的会话主体（后台用户 / 终端用户）。"""
    await _require_admin(platform_id, current_user.id, session)
    data = await list_console_conversation_principals(
        session,
        platform_id,
        page=page,
        page_size=page_size,
        principal_type=principal_type,
        keyword=keyword,
        status=status,
        include_deleted=include_deleted,
    )
    return success_response(data=data, message="conversation principals listed")


@router.get("/conversations", response_model=ApiResponse[ConsoleConversationPage])
async def list_conversations_endpoint(
    platform_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    agent_id: int | None = Query(default=None),
    principal_type: str | None = Query(default=None, pattern="^(user|end_user)$"),
    principal_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    keyword: str | None = Query(default=None),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ConsoleConversationPage]:
    """第二层：平台内会话分页列表，默认不返回已软删除的会话。"""
    _validate_dates(start_date, end_date)
    await _require_admin(platform_id, current_user.id, session)
    data = await list_console_conversations(
        session,
        platform_id,
        page=page,
        page_size=page_size,
        agent_id=agent_id,
        principal_type=principal_type,
        principal_id=principal_id,
        status=status,
        include_deleted=include_deleted,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword,
    )
    return success_response(data=data, message="conversations listed")


@router.get(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[ConsoleConversationDetail],
)
async def get_conversation_endpoint(
    platform_id: int,
    conversation_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ConsoleConversationDetail]:
    """会话详情（含会话级用量汇总）；已软删除的会话仍可打开。"""
    await _require_admin(platform_id, current_user.id, session)
    data = await get_console_conversation(session, platform_id, conversation_id)
    return success_response(data=data, message="conversation retrieved")


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ApiResponse[list[ConversationMessageRead]],
)
async def list_conversation_messages_endpoint(
    platform_id: int,
    conversation_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[list[ConversationMessageRead]]:
    """会话消息时间线。与 embed 同接口共用投影，返回裸数组、不分页。"""
    await _require_admin(platform_id, current_user.id, session)
    data = await list_console_conversation_messages(
        session, platform_id, conversation_id
    )
    return success_response(data=data, message="conversation messages listed")


@router.delete(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[None],
)
async def delete_conversation_endpoint(
    platform_id: int,
    conversation_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[None]:
    """软删除会话：只改状态，消息与用量记录保留（不做物理删除）。"""
    await _require_admin(platform_id, current_user.id, session)
    await delete_console_conversation(session, platform_id, conversation_id)
    return success_response(data=None, message="conversation deleted")
