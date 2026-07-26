import pytest
import asyncio
import socket
from pathlib import Path

from app.modules.knowledge.schemas import KnowledgeBaseUpdate
from app.modules.knowledge.runtime import validate_fetch_target
from app.modules.knowledge.services import (
    build_citations,
    next_index_version,
    split_text,
    store_file,
    validate_embedding_dimension,
    validate_fetch_url,
)
from app.shared.exceptions import BadRequestException


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
