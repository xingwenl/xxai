"""附件处理服务层：上传校验、处理版本匹配、文本切块和缓存管理。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from app.core.logging import get_logger
from app.modules.asset.models import ConversationAsset
from app.modules.asset_processing.models import (
    ConversationAssetProcessing,
    ProcessingStatus,
)
from app.modules.asset_processing.repositories import AssetProcessingRepository
from app.modules.asset_processing.runtime import (
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    PARSER_NAME,
    PARSER_VERSION,
    attachment_embedding_enabled,
    build_attachment_embedding_model,
    compute_processing_version,
    is_image_mime,
    is_text_parseable,
    load_file_text,
)
from app.modules.asset.services import resolve_asset_path
from app.shared.exceptions import BadRequestException

logger = get_logger(__name__)


def validate_asset_conversation(asset: ConversationAsset, conversation_id: int) -> None:
    """校验附件是否属于当前会话，跨会话访问抛出异常。"""
    if asset.conversation_id != conversation_id:
        raise BadRequestException("附件不属于当前会话，拒绝访问")


def validate_mime_type(mime_type: str) -> None:
    """校验 MIME 类型是否在允许列表中。"""
    from app.modules.asset_processing.runtime import ALLOWED_MIME_TYPES

    if mime_type not in ALLOWED_MIME_TYPES:
        raise BadRequestException(f"不支持的文件类型: {mime_type}")


def validate_file_size(size_bytes: int, max_bytes: int | None = None) -> None:
    """校验文件大小是否在限制内。"""
    max_bytes = max_bytes or DEFAULT_MAX_UPLOAD_BYTES
    if size_bytes <= 0:
        raise BadRequestException("文件大小必须大于 0")
    if size_bytes > max_bytes:
        raise BadRequestException(
            f"文件大小超过限制 ({size_bytes} > {max_bytes} bytes)"
        )


async def persist_uploaded_asset(
    repo,
    temp_path: Path,
    *,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    user_id: int | None,
    platform_end_user_id: int | None,
    filename: str,
    content_type: str,
    size_bytes: int,
    source_url: str = "",
) -> ConversationAsset:
    """将上传的临时文件持久化到存储并创建数据库记录。"""
    from app.modules.asset.services import persist_asset

    return await persist_asset(
        repo,
        temp_path,
        platform_id=platform_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        user_id=user_id,
        platform_end_user_id=platform_end_user_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        source_url=source_url,
    )


async def create_processing_record(
    processing_repo: AssetProcessingRepository,
    asset: ConversationAsset,
    content_hash: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> ConversationAssetProcessing:
    """为 asset 创建一条处理记录，并立即投递处理任务。"""
    processing_version = compute_processing_version(
        content_hash, PARSER_VERSION, chunk_size, chunk_overlap
    )

    # 检查是否已有相同版本的处理记录（缓存命中）
    existing = await processing_repo.get_processing_by_version(
        asset.id, processing_version
    )
    if existing is not None and existing.status == ProcessingStatus.ready:
        logger.info("处理缓存命中 asset_id=%s version=%s", asset.id, processing_version)
        return existing

    record = await processing_repo.create_processing(
        asset_id=asset.id,
        conversation_id=asset.conversation_id,
        status=ProcessingStatus.processing,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        processing_version=processing_version,
        started_at=datetime.now(timezone.utc),
    )
    return record


async def execute_processing(
    processing_repo: AssetProcessingRepository,
    asset: ConversationAsset,
    record: ConversationAssetProcessing,
) -> ConversationAssetProcessing:
    """同步执行文件解析和切块，更新处理记录状态。

    图片类型：仅标记为 ready，不解析文本。
    文档类型：解析文本、切块、保存到 storage 和数据库。
    """
    try:
        storage_path = resolve_asset_path(asset.storage_key)

        if is_image_mime(asset.content_type):
            # 图片：标记 ready，不解析文本
            return await processing_repo.update_processing(
                record,
                status=ProcessingStatus.ready,
                completed_at=datetime.now(timezone.utc),
            )

        if not is_text_parseable(asset.content_type):
            return await processing_repo.update_processing(
                record,
                status=ProcessingStatus.unsupported,
                error_message=f"不支持解析的类型: {asset.content_type}",
                completed_at=datetime.now(timezone.utc),
            )

        # 解析文本
        text = await asyncio.to_thread(
            load_file_text, str(storage_path), asset.content_type
        )

        if not text.strip():
            return await processing_repo.update_processing(
                record,
                status=ProcessingStatus.ready,
                extracted_text_storage_key=None,
                completed_at=datetime.now(timezone.utc),
            )

        # 保存解析文本到 storage
        text_storage_key = str(
            Path("assets")
            / "processed"
            / str(asset.platform_id)
            / f"{asset.asset_id}.txt"
        )
        text_target = resolve_asset_path(text_storage_key)
        await asyncio.to_thread(text_target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(text_target.write_text, text, encoding="utf-8")

        # 切块
        chunks = _split_text_to_chunks(
            text,
            chunk_size=record.chunk_size,
            chunk_overlap=record.chunk_overlap,
        )

        # 保存 chunks
        chunk_records = [
            {
                "processing_id": record.id,
                "conversation_id": asset.conversation_id,
                "asset_id": asset.id,
                "position": i,
                "content": chunk["text"],
                "page_number": chunk.get("page_number"),
                "token_count": chunk["token_count"],
            }
            for i, chunk in enumerate(chunks)
        ]
        saved_chunks = await processing_repo.create_chunks(chunk_records)

        # 会话级向量缓存：配置可用时生成并持久化，失败只降级为文本注入
        await _build_attachment_embeddings(processing_repo, record, saved_chunks)

        return await processing_repo.update_processing(
            record,
            status=ProcessingStatus.ready,
            extracted_text_storage_key=text_storage_key,
            extracted_text=text,
            completed_at=datetime.now(timezone.utc),
        )

    except Exception as exc:
        logger.exception("处理附件失败 asset_id=%s", asset.id)
        return await processing_repo.update_processing(
            record,
            status=ProcessingStatus.failed,
            error_message=str(exc)[:2000],
            completed_at=datetime.now(timezone.utc),
        )


async def _build_attachment_embeddings(
    processing_repo,
    record,
    saved_chunks: list,
) -> None:
    """按全局 embedding 配置批量生成附件切块向量并持久化。

    任何失败（服务不可用、维度不匹配等）都不影响处理状态，由网关
    降级为全文文本注入。
    """
    if not attachment_embedding_enabled():
        return
    from app.core.config import get_settings

    try:
        model = build_attachment_embedding_model()
        embeddings = await model.aget_text_embedding_batch(
            [chunk.content for chunk in saved_chunks]
        )
        dimension = get_settings().attachment_embedding_dimension
        if any(len(item) != dimension for item in embeddings):
            logger.warning(
                "附件 embedding 维度不匹配，跳过向量缓存 asset_id=%s",
                record.asset_id,
            )
            return
        await processing_repo.save_embeddings(
            [
                {
                    "chunk_id": chunk.id,
                    "processing_id": record.id,
                    "conversation_id": record.conversation_id,
                    "asset_id": record.asset_id,
                    "provider": get_settings().attachment_embedding_provider
                    or "openai",
                    "model": get_settings().attachment_embedding_model,
                    "dimension": dimension,
                    "embedding": embedding,
                }
                for chunk, embedding in zip(saved_chunks, embeddings, strict=True)
            ]
        )
    except Exception as exc:
        logger.warning(
            "附件 embedding 生成失败，降级为文本注入 asset_id=%s: %s",
            record.asset_id,
            exc,
        )


def _split_text_to_chunks(
    text: str, chunk_size: int = 512, chunk_overlap: int = 50
) -> list[dict]:
    """将文本切分为 chunks，返回包含文本、页码和 token 估算的列表。

    使用 SentenceSplitter 进行语义切分，回退为简单按字符切分。
    """
    try:
        from llama_index.core.node_parser import SentenceSplitter

        splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        nodes = splitter.get_nodes_from_documents(
            [type("_Doc", (), {"text": text, "metadata": {}})()]
        )
        return [
            {
                "text": node.text,
                "page_number": node.metadata.get("page_label"),
                "token_count": _estimate_token_count(node.text),
            }
            for node in nodes
        ]
    except Exception:
        logger.warning("SentenceSplitter 不可用，回退为简单字符切分")
        return _simple_chunk_split(text, chunk_size, chunk_overlap)


def _simple_chunk_split(text: str, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """简单按字符切分，不回退时使用。"""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end]
        chunks.append(
            {
                "text": chunk_text,
                "page_number": None,
                "token_count": _estimate_token_count(chunk_text),
            }
        )
        start += chunk_size - chunk_overlap
        if start >= len(text):
            break
    return chunks


def _estimate_token_count(text: str) -> int:
    """估算文本 token 数量（粗略按字符数/2 估算）。"""
    return max(1, len(text) // 2)
