from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.knowledge.runtime import build_embedding_model
from app.modules.knowledge.schemas import (
    DocumentRead,
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
    AgentKnowledgeBaseBind,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    UrlDocumentCreate,
)
from app.modules.knowledge.services import (
    build_citations,
    create_knowledge_base,
    store_file,
    update_knowledge_base,
    validate_embedding_dimension,
    validate_fetch_url,
)
from app.modules.knowledge.tasks import ingest_document_task
from app.modules.platform.repositories import PlatformRepository
from app.shared.exceptions import BadRequestException, NotFoundException
from app.shared.responses import ApiResponse, success_response

router = APIRouter(
    prefix="/platforms/{platform_id}/knowledge-bases", tags=["knowledge"]
)


async def _require_admin(platform_id: int, user_id: int, session: AsyncSession) -> None:
    if (
        await PlatformRepository(session).get_by_id_for_user(platform_id, user_id)
        is None
    ):
        raise NotFoundException("platform not found")


def _base_read(base) -> KnowledgeBaseRead:
    return KnowledgeBaseRead.model_validate(
        {
            **base.__dict__,
            "has_embedding_api_key": bool(base.embedding_api_key_encrypted),
        }
    )


@router.post(
    "",
    response_model=ApiResponse[KnowledgeBaseRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_base_endpoint(
    platform_id: int,
    payload: KnowledgeBaseCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    base = await create_knowledge_base(
        KnowledgeRepository(session), platform_id, payload
    )
    return success_response(data=_base_read(base), message="knowledge base created")


@router.patch("/{base_id}", response_model=ApiResponse[KnowledgeBaseRead])
async def update_base_endpoint(
    platform_id: int,
    base_id: int,
    payload: KnowledgeBaseUpdate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = KnowledgeRepository(session)
    existing = await repo.get_base(base_id, platform_id)
    if existing is None:
        raise NotFoundException("knowledge base not found")
    previous_index_version = existing.active_index_version
    base = await update_knowledge_base(repo, base_id, platform_id, payload)
    if base.active_index_version != previous_index_version:
        for document_id in await repo.queue_reindex(base.id):
            ingest_document_task.delay(document_id)
    return success_response(
        data=_base_read(base), message="knowledge base updated; reindex required"
    )


@router.post(
    "/{base_id}/documents/file",
    response_model=ApiResponse[DocumentRead],
    status_code=201,
)
async def upload_document_endpoint(
    platform_id: int,
    base_id: int,
    upload: UploadFile = File(...),
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = KnowledgeRepository(session)
    if await repo.get_base(base_id, platform_id) is None:
        raise NotFoundException("knowledge base not found")
    settings = get_settings()
    content = await upload.read(settings.agent_max_upload_bytes + 1)
    if len(content) > settings.agent_max_upload_bytes:
        raise BadRequestException("uploaded file is too large")
    path = store_file(
        Path(settings.agent_file_storage_path) / str(base_id),
        upload.filename or "",
        content,
    )
    document, _ = await repo.create_document(
        base_id,
        source_type="file",
        title=upload.filename or path.name,
        storage_path=str(path),
        media_type=upload.content_type,
    )
    ingest_document_task.delay(document.id)
    return success_response(
        data=DocumentRead.model_validate(document), message="document queued"
    )


@router.post(
    "/{base_id}/documents/url",
    response_model=ApiResponse[DocumentRead],
    status_code=201,
)
async def create_url_document_endpoint(
    platform_id: int,
    base_id: int,
    payload: UrlDocumentCreate,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = KnowledgeRepository(session)
    if await repo.get_base(base_id, platform_id) is None:
        raise NotFoundException("knowledge base not found")
    url = validate_fetch_url(payload.url)
    document, _ = await repo.create_document(
        base_id, source_type="url", title=payload.title or url, source_url=url
    )
    ingest_document_task.delay(document.id)
    return success_response(
        data=DocumentRead.model_validate(document), message="document queued"
    )


@router.get(
    "/{base_id}/documents/{document_id}", response_model=ApiResponse[DocumentRead]
)
async def get_document_endpoint(
    platform_id: int,
    base_id: int,
    document_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = KnowledgeRepository(session)
    if await repo.get_base(base_id, platform_id) is None:
        raise NotFoundException("knowledge base not found")
    document = await repo.get_document(document_id)
    if document is None or document.knowledge_base_id != base_id:
        raise NotFoundException("document not found")
    return success_response(data=DocumentRead.model_validate(document))


@router.post("/{base_id}/search", response_model=ApiResponse[KnowledgeSearchResponse])
async def search_endpoint(
    platform_id: int,
    base_id: int,
    payload: KnowledgeSearchRequest,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    repo = KnowledgeRepository(session)
    base = await repo.get_base(base_id, platform_id)
    if base is None:
        raise NotFoundException("knowledge base not found")
    embedding = await build_embedding_model(base).aget_query_embedding(payload.query)
    validate_embedding_dimension(embedding, expected_dimension=base.embedding_dimension)
    chunks = await repo.search(base, embedding, payload.limit)
    citations = build_citations(
        [
            {
                "title": chunk.source_metadata.get("title", ""),
                "source_url": chunk.source_metadata.get("source_url"),
                "content": chunk.content,
            }
            for chunk in chunks
        ]
    )
    return success_response(data=KnowledgeSearchResponse(citations=citations))


@router.put("/{base_id}/agents/{agent_id}", response_model=ApiResponse[dict])
async def bind_agent_endpoint(
    platform_id: int,
    base_id: int,
    agent_id: int,
    payload: AgentKnowledgeBaseBind,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    if payload.knowledge_base_id != base_id:
        raise BadRequestException("knowledge base id does not match path")
    binding = await KnowledgeRepository(session).bind_to_agent(
        agent_id, base_id, platform_id, payload.sort_order
    )
    if binding is None:
        raise NotFoundException("agent or knowledge base not found")
    return success_response(
        data={"agent_id": agent_id, "knowledge_base_id": base_id},
        message="knowledge base bound",
    )
