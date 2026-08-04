import asyncio

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

from app.core.database import get_session_factory
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.knowledge.runtime import build_embedding_model, load_document_content
from app.modules.knowledge.services import split_text, validate_embedding_dimension

settings = get_settings()
celery_app = Celery(
    "ai-base", broker=settings.celery_broker_url, backend=settings.celery_result_backend
)

logger = get_logger(__name__)


@celery_setup_logging.connect
def configure_worker_logging(*args, **kwargs) -> None:
    """让 Celery Worker 复用后端统一日志配置并落到宿主机日志目录。"""
    worker_settings = get_settings()
    setup_logging(
        worker_settings.log_level,
        log_file_path=worker_settings.log_file_path,
        log_file_backup_count=worker_settings.log_file_backup_count,
    )


async def ingest_document(document_id: int) -> None:
    async with get_session_factory()() as session:
        repo = KnowledgeRepository(session)
        document = await repo.get_document(document_id)
        task = await repo.get_task_for_document(document_id)
        if document is None or task is None:
            return

        logger.info('开始处理: %s, task_id: %s', document.title, task.id)
        base = await repo.get_base(document.knowledge_base_id)
        if base is None:
            return
        try:
            task.status = "processing"
            task.attempts += 1
            await session.commit()
            content = await load_document_content(document)
            chunks = split_text(
                content, chunk_size=base.chunk_size, overlap=base.chunk_overlap
            )
            embeddings = await build_embedding_model(base).aget_text_embedding_batch(
                chunks
            )
            for embedding in embeddings:
                validate_embedding_dimension(
                    embedding, expected_dimension=base.embedding_dimension
                )
            await repo.save_chunks(document, task, base, content, chunks, embeddings)
        except Exception as exc:
            await repo.mark_failed(document, task, str(exc))
            raise


@celery_app.task(
    name="knowledge.ingest_document",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def ingest_document_task(document_id: int) -> None:
    asyncio.run(ingest_document(document_id))
