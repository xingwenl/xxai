import ipaddress
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from llama_index.core.node_parser import SentenceSplitter

from app.shared.exceptions import BadRequestException
from app.modules.agent.services import encrypt_secret
from app.modules.knowledge.schemas import (
    Citation,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)
from app.shared.exceptions import ConflictException, NotFoundException

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def split_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]


def validate_embedding_dimension(
    embedding: list[float], *, expected_dimension: int
) -> None:
    if len(embedding) != expected_dimension:
        raise BadRequestException("embedding dimension mismatch")


def _is_forbidden_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def validate_fetch_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise BadRequestException("only HTTP URLs are supported")
    if not parsed.hostname or parsed.username or parsed.password:
        raise BadRequestException("invalid fetch URL")
    if _is_forbidden_ip(parsed.hostname) or parsed.hostname.lower() == "localhost":
        raise BadRequestException("fetch target is not public")
    return url


def store_file(storage_dir: Path, filename: str, content: bytes) -> Path:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise BadRequestException("unsupported file type")
    storage_dir.mkdir(parents=True, exist_ok=True)
    target = storage_dir / f"{uuid4().hex}{extension}"
    target.write_bytes(content)
    return target


def next_index_version(
    current_version: int,
    update: KnowledgeBaseUpdate,
    *,
    current_model: str,
    current_dimension: int,
) -> int:
    embedding_changed = (
        update.embedding_model is not None and update.embedding_model != current_model
    ) or (
        update.embedding_dimension is not None
        and update.embedding_dimension != current_dimension
    )
    return current_version + 1 if embedding_changed else current_version


def build_citations(matches: list[dict[str, str | None]]) -> list[Citation]:
    return [
        Citation(
            title=str(match["title"]),
            source_url=match.get("source_url"),
            text=str(match["content"]),
        )
        for match in matches
    ]


async def create_knowledge_base(repo, platform_id: int, payload: KnowledgeBaseCreate):
    if await repo.get_base_by_slug(platform_id, payload.slug) is not None:
        raise ConflictException("knowledge base slug already exists")
    stored = payload
    if payload.embedding_api_key:
        stored = payload.model_copy(
            update={"embedding_api_key": encrypt_secret(payload.embedding_api_key)}
        )
    return await repo.create_base(platform_id, stored)


async def update_knowledge_base(repo, base_id: int, platform_id: int, payload):
    base = await repo.get_base(base_id, platform_id)
    if base is None:
        raise NotFoundException("knowledge base not found")
    version = next_index_version(
        base.active_index_version,
        payload,
        current_model=base.embedding_model,
        current_dimension=base.embedding_dimension,
    )
    stored = payload
    if payload.embedding_api_key:
        stored = payload.model_copy(
            update={"embedding_api_key": encrypt_secret(payload.embedding_api_key)}
        )
    return await repo.update_base(base, stored, version)


async def retry_knowledge_document(repo, base_id: int, document_id: int):
    document = await repo.get_document(document_id)
    if document is None or document.knowledge_base_id != base_id:
        raise NotFoundException("document not found")
    if document.status != "failed":
        raise BadRequestException("only failed documents can be retried")
    return await repo.retry_document(document)
