"""附件处理记录和切块的数据访问层。"""

from __future__ import annotations

from sqlalchemy import delete, func, select
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
        min_score: float = 0.0,
    ) -> list[tuple[ConversationAssetChunk, float]]:
        """按余弦距离检索会话内指定处理版本的切块，返回（chunk, 相似度）。

        min_score 是相关度下限：pgvector 的 Top-K 检索一定会返回 k 条最相似的
        切块，哪怕用户问的内容文档里根本没有，所以必须在这里把低分结果过滤掉，
        否则调用方无法区分“确实相关”和“凑数的第 k 名”。
        """
        distance = ConversationAssetEmbedding.embedding.cosine_distance(embedding)
        statement = (
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
        if min_score > 0:
            # 相似度 = 1 - 余弦距离，等价于只保留 distance <= 1 - min_score
            statement = statement.where(distance <= 1.0 - min_score)
        result = await self.session.execute(statement)
        return [
            (chunk, max(0.0, min(1.0, 1.0 - float(distance_value))))
            for chunk, distance_value in result.all()
        ]

    async def count_chunks(
        self,
        *,
        asset_id: int,
        conversation_id: int,
        processing_id: int,
    ) -> int:
        """统计指定处理版本下的切块数量。

        用于区分“没有命中关键词”和“这份文件根本没解析出文本”：
        后者需要把原因返回给模型，否则只能看到空结果无从判断。
        """
        result = await self.session.scalar(
            select(func.count())
            .select_from(ConversationAssetChunk)
            .where(
                ConversationAssetChunk.asset_id == asset_id,
                ConversationAssetChunk.conversation_id == conversation_id,
                ConversationAssetChunk.processing_id == processing_id,
            )
        )
        return int(result or 0)

    async def search_chunks_keyword(
        self,
        *,
        asset_id: int,
        conversation_id: int,
        processing_id: int,
        terms: list[str],
        limit: int,
    ) -> list[tuple[ConversationAssetChunk, float]]:
        """按词元对切块内容做词法打分兜底检索，返回（chunk, 归一化分数）。

        未配置 embedding 时使用：对每个词元统计在切块文本中的出现次数求和，
        按最高分归一化到 0-1，保证与向量检索的返回契约一致。
        """
        if not terms:
            return []
        result = await self.session.execute(
            select(ConversationAssetChunk).where(
                ConversationAssetChunk.asset_id == asset_id,
                ConversationAssetChunk.conversation_id == conversation_id,
                ConversationAssetChunk.processing_id == processing_id,
            )
        )
        scored: list[tuple[ConversationAssetChunk, float]] = []
        for chunk in result.scalars().all():
            content = chunk.content.lower()
            score = sum(content.count(term) for term in terms)
            if score > 0:
                scored.append((chunk, float(score)))
        scored.sort(key=lambda item: item[1], reverse=True)
        if not scored:
            return []
        max_score = scored[0][1]
        return [
            (chunk, round(score / max_score, 4))
            for chunk, score in scored[:limit]
        ]

    async def delete_processing(self, record: ConversationAssetProcessing) -> None:
        await self.session.delete(record)
        await self.session.commit()
