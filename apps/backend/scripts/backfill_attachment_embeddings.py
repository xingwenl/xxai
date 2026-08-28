"""为缺失向量缓存的已处理文档附件重建 embedding（配置修正后的回填工具）。

适用场景：`.env` 中 `ATTACHMENT_EMBEDDING_DIMENSION` 与模型实际输出维度不一致时，
写入侧会跳过向量缓存，查询侧退化为全文注入。修正维度配置后运行本脚本，
可为已 ready 的文本文档处理记录补齐向量，无需重新上传文件。

运行方式（后端虚拟环境，需能连接数据库）：
    cd apps/backend && .venv/bin/python scripts/backfill_attachment_embeddings.py
    cd apps/backend && .venv/bin/python scripts/backfill_attachment_embeddings.py --asset-id 73e52f916b1d4d95ada48d4435a39eb1

说明：脚本按全局 `.env` 的 embedding 配置重建向量；若 Agent 通过模型注册表
绑定了独立 embedding 模型（role=embedding），需先确认其输出维度与全局配置一致。
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.asset.models import ConversationAsset
from app.modules.asset_processing.models import (
    ConversationAssetChunk,
    ConversationAssetEmbedding,
    ConversationAssetProcessing,
    ProcessingStatus,
)
from app.modules.asset_processing.repositories import AssetProcessingRepository
from app.modules.asset_processing.runtime import (
    attachment_embedding_enabled,
    build_attachment_embedding_model,
)


async def backfill(asset_uuid: str | None = None) -> int:
    """为缺少向量的 ready 处理记录重建 embedding，返回成功重建的处理记录数。"""
    settings = get_settings()
    if not attachment_embedding_enabled():
        print("附件 embedding 未启用（缺少维度/模型/密钥配置），无需回填")
        return 0

    session_factory = get_session_factory()
    rebuilt = 0
    async with session_factory() as session:
        processing_repo = AssetProcessingRepository(session)

        stmt = select(ConversationAssetProcessing).where(
            ConversationAssetProcessing.status == ProcessingStatus.ready
        )
        if asset_uuid:
            internal_asset_id = await session.scalar(
                select(ConversationAsset.id).where(
                    ConversationAsset.asset_id == asset_uuid
                )
            )
            if internal_asset_id is None:
                print(f"未找到 asset_id={asset_uuid}，请确认是附件 UUID 而非内部 ID")
                return 0
            stmt = stmt.where(
                ConversationAssetProcessing.asset_id == internal_asset_id
            )

        records = list((await session.execute(stmt)).scalars().all())
        print(f"发现 ready 处理记录 {len(records)} 条")

        for record in records:
            chunk_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(ConversationAssetChunk)
                    .where(ConversationAssetChunk.processing_id == record.id)
                )
                or 0
            )
            embedding_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(ConversationAssetEmbedding)
                    .where(ConversationAssetEmbedding.processing_id == record.id)
                )
                or 0
            )
            if chunk_count > 0 and embedding_count == chunk_count:
                print(
                    f"跳过 processing_id={record.id}（已有 {embedding_count} 条向量）"
                )
                continue

            chunks = await processing_repo.list_chunks(
                record.id, record.conversation_id
            )
            if not chunks:
                continue

            model = build_attachment_embedding_model()
            embeddings = await model.aget_text_embedding_batch(
                [chunk.content for chunk in chunks]
            )
            dimension = settings.attachment_embedding_dimension
            if any(len(item) != dimension for item in embeddings):
                print(
                    f"跳过 processing_id={record.id}：实际维度 "
                    f"{len(embeddings[0])} 与配置维度 {dimension} 不一致，"
                    "请先核对 ATTACHMENT_EMBEDDING_DIMENSION"
                )
                continue

            await processing_repo.save_embeddings(
                [
                    {
                        "chunk_id": chunk.id,
                        "processing_id": record.id,
                        "conversation_id": record.conversation_id,
                        "asset_id": record.asset_id,
                        "provider": settings.attachment_embedding_provider or "openai",
                        "model": settings.attachment_embedding_model,
                        "dimension": dimension,
                        "embedding": embedding,
                    }
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ]
            )
            rebuilt += 1
            print(
                f"已重建 processing_id={record.id} asset_id={record.asset_id} "
                f"chunks={len(chunks)}"
            )
    return rebuilt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重建附件 embedding 向量缓存")
    parser.add_argument(
        "--asset-id",
        help="只重建指定附件 UUID 的处理记录，缺省重建全部 ready 文档",
    )
    args = parser.parse_args()
    result = asyncio.run(backfill(asset_uuid=args.asset_id))
    print(f"回填完成，共重建 {result} 条处理记录")
