"""会话附件的上传、状态查询和删除接口。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.logging import get_logger
from app.modules.asset.repositories import AssetRepository
from app.modules.asset.schemas import (
    AssetStatus,
    AssetStatusResponse,
    AssetUploadResponse,
)
from app.modules.asset.services import resolve_asset_path
from app.modules.asset_processing.models import ProcessingStatus
from app.modules.asset_processing.repositories import AssetProcessingRepository
from app.modules.asset_processing.runtime import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    compute_file_hash,
)
from app.modules.asset_processing.services import (
    create_processing_record,
    execute_processing,
    persist_uploaded_asset,
    validate_file_size,
    validate_mime_type,
)
from app.modules.conversation.repositories import ConversationRepository
from app.modules.embed.security import get_current_embed_claims
from app.shared.exceptions import BadRequestException, NotFoundException

logger = get_logger(__name__)

# 需要 conversation_id 的接口（查询和删除）
conversation_router = APIRouter(
    prefix="/embed/conversations/{conversation_id}/assets",
    tags=["conversation-assets"],
)

# 首次上传接口（自动创建会话，无需 conversation_id）
upload_router = APIRouter(prefix="/embed/assets", tags=["conversation-assets"])


def _map_status(status: str) -> AssetStatus:
    mapping = {
        ProcessingStatus.uploaded: AssetStatus.uploaded,
        ProcessingStatus.processing: AssetStatus.processing,
        ProcessingStatus.ready: AssetStatus.ready,
        ProcessingStatus.failed: AssetStatus.failed,
        ProcessingStatus.unsupported: AssetStatus.unsupported,
    }
    return mapping.get(status, AssetStatus.uploaded)


async def _ensure_conversation(
    session: AsyncSession,
    platform_id: int,
    agent_id: int,
    end_user_id: int,
    title: str = "新会话",
) -> int:
    """确保当前主体有一个活跃会话，不存在则创建。"""
    repo = ConversationRepository(session)
    # 如果还没有 conversation_id，自动创建会话
    conversation = await repo.create_for_principal(
        platform_id=platform_id,
        agent_id=agent_id,
        end_user_id=end_user_id,
        title=title[:255],
    )
    logger.info("自动创建会话 conversation_id=%s platform_id=%s end_user_id=%s", conversation.id, platform_id, end_user_id)
    return conversation.id


async def _do_upload(
    session: AsyncSession,
    file: UploadFile,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    end_user_id: int,
) -> dict:
    """执行上传、持久化和处理流程，返回 API 响应数据。"""
    if not file.filename:
        raise BadRequestException("文件名不能为空")
    content_type = file.content_type or "application/octet-stream"
    validate_mime_type(content_type)

    body = await file.read()
    validate_file_size(len(body))

    tmp = Path(tempfile.mkdtemp()) / (file.filename or "upload")
    tmp.write_bytes(body)

    try:
        asset_repo = AssetRepository(session)
        asset = await persist_uploaded_asset(
            asset_repo,
            tmp,
            platform_id=platform_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_id=None,
            platform_end_user_id=end_user_id,
            filename=file.filename,
            content_type=content_type,
            size_bytes=len(body),
        )
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        try:
            tmp.parent.rmdir()
        except OSError:
            pass

    processing_repo = AssetProcessingRepository(session)
    storage_path = resolve_asset_path(asset.storage_key)
    content_hash = compute_file_hash(storage_path)
    record = await create_processing_record(
        processing_repo, asset, content_hash,
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    )
    record = await execute_processing(processing_repo, asset, record)

    return AssetUploadResponse(
        assetId=asset.asset_id,
        filename=asset.filename,
        mimeType=asset.content_type,
        size=asset.size_bytes,
        status=_map_status(record.status),
        createdAt=asset.created_at,
    # JSONResponse 不会自动编码 datetime，必须让 Pydantic 先转换为 ISO 8601 字符串。
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# 首次上传接口（自动创建会话）
# ---------------------------------------------------------------------------

@upload_router.post("")
async def upload_asset_auto_conversation(
    file: UploadFile = File(...),
    claims=Depends(get_current_embed_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """上传附件，自动创建会话（适用于首次上传时还没有 conversation_id 的场景）。"""
    platform_id = int(claims["platform_id"])
    agent_id = int(claims["agent_id"])
    end_user_id = int(claims["sub"])

    conversation_id = await _ensure_conversation(
        session, platform_id, agent_id, end_user_id,
        title=file.filename or "新会话",
    )

    data = await _do_upload(
        session, file, platform_id, agent_id, conversation_id, end_user_id,
    )

    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "message": "ok",
            "code": 0,
            "data": {**data, "conversationId": conversation_id},
        },
    )


# ---------------------------------------------------------------------------
# 已有会话的上传接口
# ---------------------------------------------------------------------------

@conversation_router.post("")
async def upload_conversation_asset(
    conversation_id: int,
    file: UploadFile = File(...),
    claims=Depends(get_current_embed_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """上传附件到指定会话（已有会话时使用）。"""
    platform_id = int(claims["platform_id"])
    agent_id = int(claims["agent_id"])
    end_user_id = int(claims["sub"])

    data = await _do_upload(
        session, file, platform_id, agent_id, conversation_id, end_user_id,
    )

    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "message": "ok",
            "code": 0,
            "data": data,
        },
    )


@conversation_router.get("/{asset_id}")
async def get_asset_status(
    conversation_id: int,
    asset_id: str,
    claims=Depends(get_current_embed_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """查询附件处理状态和已解析的 chunks。"""
    asset_repo = AssetRepository(session)
    asset = await asset_repo.get_for_embed_conversation(
        asset_id,
        platform_id=int(claims["platform_id"]),
        agent_id=int(claims["agent_id"]),
        end_user_id=int(claims["sub"]),
        conversation_id=conversation_id,
    )
    if asset is None:
        raise NotFoundException("asset not found")

    processing_repo = AssetProcessingRepository(session)
    record = await processing_repo.get_processing(asset.id, conversation_id)

    chunks = []
    if record is not None:
        chunk_records = await processing_repo.list_chunks(record.id, conversation_id)
        chunks = [
            {
                "position": c.position,
                "content": c.content,
                "pageNumber": c.page_number,
                "tokenCount": c.token_count,
            }
            for c in chunk_records
        ]

    return JSONResponse(
        content={
            "success": True,
            "message": "ok",
            "code": 0,
            "data": AssetStatusResponse(
                assetId=asset.asset_id,
                filename=asset.filename,
                mimeType=asset.content_type,
                size=asset.size_bytes,
                status=_map_status(record.status if record else ProcessingStatus.uploaded),
                errorMessage=record.error_message if record else None,
                chunks=chunks,
                createdAt=asset.created_at,
                completedAt=record.completed_at if record else None,
            ).model_dump(),
        },
    )


@conversation_router.delete("/{asset_id}")
async def delete_asset(
    conversation_id: int,
    asset_id: str,
    claims=Depends(get_current_embed_claims),
    session: AsyncSession = Depends(get_db_session),
):
    """删除附件及其所有派生数据。"""
    asset_repo = AssetRepository(session)
    asset = await asset_repo.get_for_embed_conversation(
        asset_id,
        platform_id=int(claims["platform_id"]),
        agent_id=int(claims["agent_id"]),
        end_user_id=int(claims["sub"]),
        conversation_id=conversation_id,
    )
    if asset is None:
        raise NotFoundException("asset not found")

    processing_repo = AssetProcessingRepository(session)
    record = await processing_repo.get_processing(asset.id, conversation_id)
    if record is not None:
        await processing_repo.delete_chunks_by_processing(record.id)
        await processing_repo.delete_processing(record)

    storage_path = resolve_asset_path(asset.storage_key)
    if storage_path.exists():
        storage_path.unlink(missing_ok=True)

    await asset_repo.session.delete(asset)
    await asset_repo.session.commit()

    return JSONResponse(
        content={"success": True, "message": "附件已删除", "code": 0, "data": None},
    )
