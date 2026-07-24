import pytest

from app.modules.knowledge.services import (
    split_text,
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
