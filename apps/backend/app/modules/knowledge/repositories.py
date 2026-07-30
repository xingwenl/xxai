from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.models import (
    AgentKnowledgeBase,
    IngestionTask,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.modules.knowledge.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.shared.pagination import PaginationParams, build_page_data


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

    async def list_bases(self, platform_id: int, params: PaginationParams):
        statement = (
            select(KnowledgeBase)
            .where(KnowledgeBase.platform_id == platform_id)
            .order_by(KnowledgeBase.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        items = list((await self.session.execute(statement)).scalars().all())
        total = await self.session.scalar(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.platform_id == platform_id)
        )
        return build_page_data(items, params, int(total or 0))

    async def list_enabled_for_agent(self, agent_id: int, platform_id: int):
        result = await self.session.execute(
            select(KnowledgeBase)
            .join(
                AgentKnowledgeBase,
                AgentKnowledgeBase.knowledge_base_id == KnowledgeBase.id,
            )
            .where(
                AgentKnowledgeBase.agent_id == agent_id,
                AgentKnowledgeBase.is_enabled.is_(True),
                KnowledgeBase.platform_id == platform_id,
            )
            .order_by(AgentKnowledgeBase.sort_order, KnowledgeBase.id)
        )
        return list(result.scalars().all())

    async def bind_to_agent(
        self, agent_id: int, knowledge_base_id: int, platform_id: int, sort_order: int
    ):
        from app.modules.agent.models import Agent

        agent = await self.session.scalar(
            select(Agent).where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        base = await self.get_base(knowledge_base_id, platform_id)
        if agent is None or base is None:
            return None
        binding = await self.session.scalar(
            select(AgentKnowledgeBase).where(
                AgentKnowledgeBase.agent_id == agent_id,
                AgentKnowledgeBase.knowledge_base_id == knowledge_base_id,
            )
        )
        if binding is None:
            binding = AgentKnowledgeBase(
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                sort_order=sort_order,
            )
            self.session.add(binding)
        else:
            binding.is_enabled = True
            binding.sort_order = sort_order
        await self.session.commit()
        await self.session.refresh(binding)
        return binding

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

    async def list_documents(self, base_id: int):
        result = await self.session.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == base_id)
            .order_by(KnowledgeDocument.id.desc())
        )
        return list(result.scalars().all())

    async def delete_base(self, base: KnowledgeBase) -> list[str]:
        documents = await self.list_documents(base.id)
        storage_paths = [
            document.storage_path
            for document in documents
            if document.storage_path
        ]
        await self.session.delete(base)
        await self.session.commit()
        return storage_paths

    async def delete_document(self, document: KnowledgeDocument) -> str | None:
        storage_path = document.storage_path
        await self.session.delete(document)
        await self.session.commit()
        return storage_path

    async def retry_document(self, document: KnowledgeDocument):
        document.status = "pending"
        document.error_message = None
        task = IngestionTask(
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            status="queued",
            attempts=0,
            error_message=None,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(document)
        return document

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
