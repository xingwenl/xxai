import ipaddress
from urllib.parse import urlsplit

from llama_index.core.node_parser import SentenceSplitter

from app.shared.exceptions import BadRequestException


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
