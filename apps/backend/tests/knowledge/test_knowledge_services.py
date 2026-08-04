import pytest
import asyncio
import socket
from pathlib import Path

from app.modules.knowledge.schemas import KnowledgeBaseUpdate
from app.modules.knowledge.runtime import resolve_storage_path, validate_fetch_target
from app.modules.knowledge.services import (
    build_citations,
    next_index_version,
    split_text,
    store_file,
    validate_embedding_dimension,
    validate_fetch_url,
    retry_knowledge_document,
)
from app.shared.exceptions import BadRequestException


class FakeDocument:
    def __init__(self, status: str) -> None:
        self.id = 7
        self.knowledge_base_id = 3
        self.status = status


class FakeRetryRepository:
    def __init__(self, document: FakeDocument) -> None:
        self.document = document
        self.retried = False

    async def get_document(self, document_id: int):
        return self.document if document_id == self.document.id else None

    async def retry_document(self, document: FakeDocument):
        self.retried = True
        document.status = "pending"
        return document


class FakeBase:
    def __init__(
        self,
        *,
        embedding_base_url: str | None,
        embedding_model: str = "text-embedding-3-small",
        embedding_api_key_encrypted=None,
    ):
        self.embedding_model = embedding_model
        self.embedding_base_url = embedding_base_url
        self.embedding_api_key_encrypted = embedding_api_key_encrypted


def test_split_text_uses_configured_chunk_size() -> None:
    chunks = split_text("one two three four five six", chunk_size=2, overlap=0)

    assert len(chunks) > 1
    assert "".join(chunks).replace(" ", "") == "onetwothreefourfivesix"


def test_embedding_dimension_must_match_knowledge_base() -> None:
    with pytest.raises(BadRequestException, match="embedding dimension mismatch"):
        validate_embedding_dimension([0.1, 0.2], expected_dimension=3)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://user:pass@example.com/secret",
    ],
)
def test_fetch_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(BadRequestException):
        validate_fetch_url(url)


def test_fetch_url_accepts_public_http_url() -> None:
    assert validate_fetch_url("https://example.com/docs") == "https://example.com/docs"


def test_store_file_uses_generated_name_and_preserves_allowed_extension(
    tmp_path: Path,
) -> None:
    stored = store_file(tmp_path, "manual.pdf", b"pdf-content")

    assert stored.suffix == ".pdf"
    assert stored.name != "manual.pdf"
    assert stored.read_bytes() == b"pdf-content"


def test_store_file_rejects_unsupported_extension(tmp_path: Path) -> None:
    with pytest.raises(BadRequestException, match="unsupported file type"):
        store_file(tmp_path, "script.py", b"print('unsafe')")


def test_build_embedding_model_uses_dummy_key_for_local_base_url() -> None:
    from app.modules.knowledge.runtime import build_embedding_model

    model = build_embedding_model(
        FakeBase(
            embedding_base_url="http://ollama:11434/v1",
            embedding_model="embeddinggemma",
        )
    )

    assert model.api_key == "ollama"
    assert model.model_name == "embeddinggemma"
    assert model._text_engine == "embeddinggemma"


def test_build_embedding_model_keeps_missing_key_for_remote_base_url() -> None:
    from app.modules.knowledge.runtime import build_embedding_model

    model = build_embedding_model(FakeBase(embedding_base_url="https://api.openai.com/v1"))

    assert not model.api_key


def test_build_embedding_model_supports_dashscope_model_names() -> None:
    from app.modules.knowledge.runtime import build_embedding_model

    model = build_embedding_model(
        FakeBase(
            embedding_base_url="https://embedding-proxy.example.com/v1",
            embedding_model="text-embedding-v3",
        )
    )

    assert model.model_name == "text-embedding-v3"
    assert model._text_engine == "text-embedding-v3"


def test_build_embedding_model_keeps_openai_model_enum_behavior() -> None:
    from app.modules.knowledge.runtime import build_embedding_model

    model = build_embedding_model(
        FakeBase(
            embedding_base_url="https://embedding-proxy.example.com/v1",
            embedding_model="text-embedding-3-small",
        )
    )

    assert model.model_name == "text-embedding-3-small"
    assert model._text_engine == "text-embedding-3-small"


def test_resolve_storage_path_rebases_host_storage_path_for_worker() -> None:
    resolved = resolve_storage_path(
        "/Users/dev/project/apps/backend/storage/3/manual.md",
        storage_root="/app/storage",
    )

    assert resolved == Path("/app/storage/3/manual.md")


def test_resolve_storage_path_uses_configured_root_for_relative_path() -> None:
    resolved = resolve_storage_path("3/manual.md", storage_root="/app/storage")

    assert resolved == Path("/app/storage/3/manual.md")


def test_embedding_change_creates_new_index_version() -> None:
    update = KnowledgeBaseUpdate(embedding_model="text-embedding-3-large")

    assert (
        next_index_version(
            3, update, current_model="text-embedding-3-small", current_dimension=1536
        )
        == 4
    )


def test_chunk_change_does_not_create_new_embedding_index_version() -> None:
    update = KnowledgeBaseUpdate(chunk_size=256)

    assert (
        next_index_version(
            3, update, current_model="text-embedding-3-small", current_dimension=1536
        )
        == 3
    )


def test_build_citations_contains_source_and_matched_text() -> None:
    citations = build_citations(
        [
            {
                "title": "手册",
                "source_url": "https://example.com/manual",
                "content": "退款规则",
            }
        ]
    )

    assert citations[0].title == "手册"
    assert citations[0].source_url == "https://example.com/manual"
    assert citations[0].text == "退款规则"


def test_failed_document_can_be_retried() -> None:
    async def run() -> None:
        repo = FakeRetryRepository(FakeDocument("failed"))

        document = await retry_knowledge_document(repo, base_id=3, document_id=7)

        assert document.status == "pending"
        assert repo.retried is True

    asyncio.run(run())


def test_ready_document_cannot_be_retried() -> None:
    async def run() -> None:
        repo = FakeRetryRepository(FakeDocument("ready"))

        with pytest.raises(BadRequestException, match="only failed documents"):
            await retry_knowledge_document(repo, base_id=3, document_id=7)

        assert repo.retried is False

    asyncio.run(run())


def test_fetch_target_rejects_hostname_resolving_to_private_ip(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 0))
        ],
    )

    with pytest.raises(BadRequestException, match="not public"):
        asyncio.run(validate_fetch_target("https://internal.example.test/data"))
