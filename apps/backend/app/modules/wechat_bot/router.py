"""微信助手后台管理接口。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.repositories import PlatformRepository
from app.modules.wechat_bot.repositories import WeChatBotBindingRepository
from app.modules.wechat_bot.schemas import (
    WeChatBotBindingCreate,
    WeChatBotBindingCreated,
    WeChatBotBindingRead,
    WeChatBotBindingStatusRead,
    WeChatBotBindingUpdate,
    WeChatBotVerifyCodeRequest,
)
from app.modules.wechat_bot.services import (
    create_binding,
    deactivate_binding,
    poll_binding_status,
)
from app.shared.exceptions import NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(
    prefix="/platforms/{platform_id}/wechat-bots", tags=["wechat-bots"]
)


async def _require_platform_admin(
    platform_id: int, user_id: int, session: AsyncSession
) -> None:
    platform = await PlatformRepository(session).get_by_id_for_user(
        platform_id, user_id
    )
    if platform is None:
        raise NotFoundException("platform not found")


def _read(binding) -> WeChatBotBindingRead:
    return WeChatBotBindingRead.model_validate(binding)


@router.get("", response_model=ApiResponse[list[WeChatBotBindingRead]])
async def list_bindings(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[list[WeChatBotBindingRead]]:
    await _require_platform_admin(platform_id, current_user.id, session)
    bindings = await WeChatBotBindingRepository(session).list_for_user(
        platform_id, current_user.id
    )
    return success_response(data=[_read(item) for item in bindings])


@router.post(
    "",
    response_model=ApiResponse[WeChatBotBindingCreated],
    status_code=status.HTTP_201_CREATED,
)
async def create_binding_endpoint(
    platform_id: int,
    payload: WeChatBotBindingCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WeChatBotBindingCreated]:
    await _require_platform_admin(platform_id, current_user.id, session)
    binding, api_token = await create_binding(
        WeChatBotBindingRepository(session),
        platform_id=platform_id,
        user_id=current_user.id,
        agent_id=payload.agent_id,
    )
    return success_response(
        data=WeChatBotBindingCreated(
            binding=_read(binding),
            qrcode=binding.qrcode or "",
            api_token=api_token,
        ),
        message="wechat bot binding created, scan qrcode to activate",
    )


@router.get(
    "/{binding_id}/status",
    response_model=ApiResponse[WeChatBotBindingStatusRead],
)
async def binding_status_endpoint(
    platform_id: int,
    binding_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WeChatBotBindingStatusRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    repo = WeChatBotBindingRepository(session)
    binding = await repo.get_for_user(binding_id, platform_id, current_user.id)
    if binding is None:
        raise NotFoundException("wechat bot binding not found")
    state = await poll_binding_status(repo, binding)
    message = {
        "wait": "等待扫码",
        "scaned": "已扫码，请在微信中确认",
        "confirmed": "绑定成功",
        "expired": "二维码已过期",
        "binded_redirect": "该微信号已绑定其他机器人",
        "need_verifycode": "请在微信中查看配对码并提交",
        "verify_code_blocked": "配对码错误次数过多，请重新绑定",
        "error": "状态查询失败",
    }.get(state, "未知状态")
    return success_response(
        data=WeChatBotBindingStatusRead(
            status=state,
            message=binding.last_error or message,
            last_login_at=binding.last_login_at,
        )
    )


@router.post(
    "/{binding_id}/verify-code",
    response_model=ApiResponse[WeChatBotBindingStatusRead],
)
async def submit_verify_code_endpoint(
    platform_id: int,
    binding_id: int,
    payload: WeChatBotVerifyCodeRequest,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WeChatBotBindingStatusRead]:
    """提交扫码配对码并立即轮询一次（need_verifycode 流程）。"""
    await _require_platform_admin(platform_id, current_user.id, session)
    repo = WeChatBotBindingRepository(session)
    binding = await repo.get_for_user(binding_id, platform_id, current_user.id)
    if binding is None:
        raise NotFoundException("wechat bot binding not found")
    binding = await repo.update(
        binding, pending_verify_code=payload.verify_code.strip()
    )
    state = await poll_binding_status(repo, binding)
    return success_response(
        data=WeChatBotBindingStatusRead(
            status=state,
            message=state,
            last_login_at=binding.last_login_at,
        )
    )


@router.patch("/{binding_id}", response_model=ApiResponse[WeChatBotBindingRead])
async def update_binding_endpoint(
    platform_id: int,
    binding_id: int,
    payload: WeChatBotBindingUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WeChatBotBindingRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    repo = WeChatBotBindingRepository(session)
    binding = await repo.get_for_user(binding_id, platform_id, current_user.id)
    if binding is None:
        raise NotFoundException("wechat bot binding not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes:
        binding = await repo.update(binding, **changes)
    return success_response(data=_read(binding))


@router.delete("/{binding_id}", response_model=ApiResponse[None])
async def delete_binding_endpoint(
    platform_id: int,
    binding_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[None]:
    await _require_platform_admin(platform_id, current_user.id, session)
    repo = WeChatBotBindingRepository(session)
    binding = await repo.get_for_user(binding_id, platform_id, current_user.id)
    if binding is None:
        raise NotFoundException("wechat bot binding not found")
    await deactivate_binding(repo, binding)
    return success_response(message="wechat bot binding deleted")
