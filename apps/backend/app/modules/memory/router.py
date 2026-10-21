"""用户记忆的本人视图接口。

路径挂在 ``/platforms/{platform_id}/me/memories``：记忆只属于「当前登录用户」，
没有管理员代查入口——管理侧只暴露条数与更新时间（见 ``/me/memories/stats`` 的
口径说明），内容本身只有本人能读。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.memory.principal import MemoryPrincipal, user_principal
from app.modules.memory.repositories import MemoryRepository
from app.modules.memory.schemas import (
    MemoryCreate,
    MemoryKind,
    MemoryListData,
    MemoryRead,
    MemoryUpdate,
    memory_read,
)
from app.modules.memory.services import MODE_EXPLICIT, normalize_kind, remember_memory
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(
    prefix="/platforms/{platform_id}/me/memories", tags=["memory"]
)


async def _require_member(platform_id: int, user_id: int, session: AsyncSession) -> None:
    if (
        await PlatformRepository(session).get_by_id_for_user(platform_id, user_id)
        is None
    ):
        raise NotFoundException("platform not found")


def _principal(platform_id: int, user_id: int) -> MemoryPrincipal:
    """本人视图只服务后台用户主体；终端用户没有后台登录态，不会走到这里。"""

    return user_principal(platform_id, user_id)


async def _require_own_memory(
    repo: MemoryRepository, *, principal: MemoryPrincipal, memory_id: int
):
    row = await repo.get_by_id(memory_id)
    # 别人的记忆一律按「不存在」处理：返回 403 会暴露某条 id 确实属于别人。
    if row is None or not principal.owns(row):
        raise NotFoundException("memory not found")
    return row


@router.get("", response_model=ApiResponse[MemoryListData])
async def list_memories_endpoint(
    platform_id: int,
    kind: MemoryKind | None = Query(default=None, description="只看某一类记忆"),
    include_history: bool = Query(
        default=False, description="是否包含已被新值覆盖的历史事实"
    ),
    query: str | None = Query(default=None, max_length=100, description="关键词过滤"),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_member(platform_id, current_user.id, session)
    repo = MemoryRepository(session)
    principal = _principal(platform_id, current_user.id)
    rows = await repo.list_for(
        principal,
        kind=normalize_kind(kind) if kind else None,
        include_history=include_history,
        query=query,
        limit=500,
    )
    fact_count, event_count = await repo.count_active_by_kind(principal)
    return success_response(
        data=MemoryListData(
            items=[memory_read(row) for row in rows],
            total=len(rows),
            fact_count=fact_count,
            event_count=event_count,
        )
    )


@router.post("", response_model=ApiResponse[MemoryRead])
async def create_memory_endpoint(
    platform_id: int,
    payload: MemoryCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_member(platform_id, current_user.id, session)
    repo = MemoryRepository(session)
    # 手填走 explicit：用户亲自输入的条目不受自动写入的白名单与敏感类别限制。
    result = await remember_memory(
        repo,
        principal=_principal(platform_id, current_user.id),
        kind=payload.kind,
        key=payload.key,
        content=payload.content,
        occurred_at=payload.occurred_at,
        mode=MODE_EXPLICIT,
    )
    row = await repo.get_by_id(result["id"])
    return success_response(data=memory_read(row), message=result["message"])


@router.patch("/{memory_id}", response_model=ApiResponse[MemoryRead])
async def update_memory_endpoint(
    platform_id: int,
    memory_id: int,
    payload: MemoryUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_member(platform_id, current_user.id, session)
    repo = MemoryRepository(session)
    row = await _require_own_memory(
        repo,
        principal=_principal(platform_id, current_user.id),
        memory_id=memory_id,
    )
    if payload.content is None and payload.occurred_at is None:
        return success_response(data=memory_read(row))
    row = await repo.update_content(
        row,
        content=payload.content if payload.content is not None else row.content,
        occurred_at=payload.occurred_at,
    )
    return success_response(data=memory_read(row), message="记忆已更新")


@router.delete("/{memory_id}", response_model=ApiResponse[None])
async def delete_memory_endpoint(
    platform_id: int,
    memory_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_member(platform_id, current_user.id, session)
    repo = MemoryRepository(session)
    row = await _require_own_memory(
        repo,
        principal=_principal(platform_id, current_user.id),
        memory_id=memory_id,
    )
    await repo.delete(row)
    return success_response(message="记忆已删除")


@router.delete("", response_model=ApiResponse[None])
async def delete_all_memories_endpoint(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_member(platform_id, current_user.id, session)
    repo = MemoryRepository(session)
    deleted = await repo.delete_all_for(
        _principal(platform_id, current_user.id)
    )
    return success_response(data={"deleted": deleted}, message="记忆已清空")


@router.get("/stats", response_model=ApiResponse[dict])
async def memory_stats_endpoint(
    platform_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    """只返回条数——管理侧如需展示「这位用户有多少记忆」，也走这条口径。"""

    await _require_member(platform_id, current_user.id, session)
    repo = MemoryRepository(session)
    fact_count, event_count = await repo.count_active_by_kind(
        _principal(platform_id, current_user.id)
    )
    return success_response(
        data={
            "fact_count": fact_count,
            "event_count": event_count,
            "total": fact_count + event_count,
        }
    )
