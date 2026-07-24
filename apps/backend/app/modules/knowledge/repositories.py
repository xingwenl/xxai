from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.models import (
    IngestionTask,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.modules.knowledge.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_base(self, base_id: int, platform_id: int | None = None):
        statement = select(KnowledgeBase).where(KnowledgeBase.id == base_id)
        if platform_id is not None:
            statement = statement.where(KnowledgeBase.platform_id == platform_id)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_base_by_slug(self, platform_id: int, slug: str):
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.platform_id == platform_id, KnowledgeBase.slug == slug
            )
        )
        return result.scalar_one_or_none()

    async def create_base(self, platform_id: int, payload: KnowledgeBaseCreate):
        values = payload.model_dump(exclude={"embedding_api_key"})
        values["embedding_api_key_encrypted"] = payload.embedding_api_key
        base = KnowledgeBase(platform_id=platform_id, **values)
        self.session.add(base)
        await self.session.commit()
        await self.session.refresh(base)
        return base

    async def update_base(
        self, base: KnowledgeBase, payload: KnowledgeBaseUpdate, index_version: int
    ):
        values = payload.model_dump(
            exclude_unset=True, exclude_none=True, exclude={"embedding_api_key"}
        )
        if payload.embedding_api_key is not None:
            values["embedding_api_key_encrypted"] = payload.embedding_api_key
        values["active_index_version"] = index_version
        for key, value in values.items():
            setattr(base, key, value)
        await self.session.commit()
        await self.session.refresh(base)
        return base

    async def create_document(self, base_id: int, **values):
        document = KnowledgeDocument(knowledge_base_id=base_id, **values)
        self.session.add(document)
        await self.session.flush()
        task = IngestionTask(knowledge_base_id=base_id, document_id=document.id)
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(document)
        await self.session.refresh(task)
        return document, task

    async def get_document(self, document_id: int):
        return await self.session.get(KnowledgeDocument, document_id)

    async def get_task_for_document(self, document_id: int):
        result = await self.session.execute(
            select(IngestionTask)
            .where(IngestionTask.document_id == document_id)
            .order_by(IngestionTask.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def queue_reindex(self, base_id: int) -> list[int]:
        documents = list(
            (
                await self.session.execute(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.knowledge_base_id == base_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for document in documents:
            document.status = "pending"
            self.session.add(
                IngestionTask(
                    knowledge_base_id=base_id,
                    document_id=document.id,
                    status="queued",
                )
            )
        await self.session.commit()
        return [document.id for document in documents]

    async def save_chunks(self, document, task, base, content: str, chunks, embeddings):
        await self.session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document.id,
                KnowledgeChunk.index_version == base.active_index_version,
            )
        )
        self.session.add_all(
            [
                KnowledgeChunk(
                    knowledge_base_id=base.id,
                    document_id=document.id,
                    index_version=base.active_index_version,
                    position=position,
                    content=chunk,
                    source_metadata={
                        "title": document.title,
                        "source_url": document.source_url,
                    },
                    embedding=embedding,
                )
                for position, (chunk, embedding) in enumerate(
                    zip(chunks, embeddings, strict=True)
                )
            ]
        )
        document.content = content
        document.status = "ready"
        task.status = "completed"
        await self.session.commit()

    async def mark_failed(self, document, task, message: str):
        document.status = "failed"
        document.error_message = message[:2000]
        task.status = "failed"
        task.error_message = message[:2000]
        task.attempts += 1
        await self.session.commit()

    async def search(self, base, embedding: list[float], limit: int):
        distance = KnowledgeChunk.embedding.cosine_distance(embedding)
        result = await self.session.execute(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.knowledge_base_id == base.id,
                KnowledgeChunk.index_version == base.active_index_version,
            )
            .order_by(distance)
            .limit(limit)
        )
        return list(result.scalars())
