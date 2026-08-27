"""附件处理记录和切块的数据访问层。"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.asset_processing.models import (
    ConversationAssetChunk,
    ConversationAssetEmbedding,
    ConversationAssetProcessing,
)


class AssetProcessingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_processing(self, **values) -> ConversationAssetProcessing:
        record = ConversationAssetProcessing(**values)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_processing(
        self, asset_id: int, conversation_id: int
    ) -> ConversationAssetProcessing | None:
        return await self.session.scalar(
            select(ConversationAssetProcessing).where(
                ConversationAssetProcessing.asset_id == asset_id,
                ConversationAssetProcessing.conversation_id == conversation_id,
            )
        )

    async def get_processing_by_version(
        self, asset_id: int, processing_version: str
    ) -> ConversationAssetProcessing | None:
        return await self.session.scalar(
            select(ConversationAssetProcessing)
            .where(
                ConversationAssetProcessing.asset_id == asset_id,
                ConversationAssetProcessing.processing_version == processing_version,
            )
            .order_by(ConversationAssetProcessing.id.desc())
            .limit(1)
        )

    async def update_processing(
        self, record: ConversationAssetProcessing, **values
    ) -> ConversationAssetProcessing:
        for key, value in values.items():
            setattr(record, key, value)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def create_chunks(self, chunks: list[dict]) -> list[ConversationAssetChunk]:
        records = [ConversationAssetChunk(**chunk) for chunk in chunks]
        self.session.add_all(records)
        await self.session.commit()
        return records

    async def list_chunks(
        self, processing_id: int, conversation_id: int
    ) -> list[ConversationAssetChunk]:
        result = await self.session.execute(
            select(ConversationAssetChunk)
            .where(
                ConversationAssetChunk.processing_id == processing_id,
                ConversationAssetChunk.conversation_id == conversation_id,
            )
            .order_by(ConversationAssetChunk.position)
        )
        return list(result.scalars().all())

    async def list_chunks_by_asset(
        self, asset_id: int, conversation_id: int
    ) -> list[ConversationAssetChunk]:
        result = await self.session.execute(
            select(ConversationAssetChunk)
            .where(
                ConversationAssetChunk.asset_id == asset_id,
                ConversationAssetChunk.conversation_id == conversation_id,
            )
            .order_by(ConversationAssetChunk.position)
        )
        return list(result.scalars().all())

    async def delete_chunks_by_processing(self, processing_id: int) -> None:
        records = await self.session.execute(
            select(ConversationAssetChunk).where(
                ConversationAssetChunk.processing_id == processing_id,
            )
        )
        for record in records.scalars().all():
            await self.session.delete(record)
        await self.session.commit()

    async def save_embeddings(self, embeddings: list[dict]) -> None:
        """整批重建某处理记录的向量：先删旧向量再插入，保证版本一致。"""
        if not embeddings:
            return
        processing_id = embeddings[0]["processing_id"]
        await self.session.execute(
            delete(ConversationAssetEmbedding).where(
                ConversationAssetEmbedding.processing_id == processing_id
            )
        )
        self.session.add_all(
            [ConversationAssetEmbedding(**item) for item in embeddings]
        )
        await self.session.commit()

    async def search_chunks(
        self,
        *,
        asset_id: int,
        conversation_id: int,
        processing_id: int,
        embedding: list[float],
        limit: int,
    ) -> list[tuple[ConversationAssetChunk, float]]:
        """按余弦距离检索会话内指定处理版本的切块，返回（chunk, 相似度）。"""
        distance = ConversationAssetEmbedding.embedding.cosine_distance(embedding)
        result = await self.session.execute(
            select(ConversationAssetChunk, distance.label("distance"))
            .join(
                ConversationAssetEmbedding,
                ConversationAssetEmbedding.chunk_id == ConversationAssetChunk.id,
            )
            .where(
                ConversationAssetChunk.asset_id == asset_id,
                ConversationAssetChunk.conversation_id == conversation_id,
                ConversationAssetEmbedding.processing_id == processing_id,
            )
            .order_by(distance)
            .limit(limit)
        )
        return [
            (chunk, max(0.0, min(1.0, 1.0 - float(distance_value))))
            for chunk, distance_value in result.all()
        ]

    async def delete_processing(self, record: ConversationAssetProcessing) -> None:
        await self.session.delete(record)
        await self.session.commit()
