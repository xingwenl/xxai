import asyncio
import socket
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from llama_index.core import SimpleDirectoryReader
from llama_index.embeddings.openai import OpenAIEmbedding

from app.core.config import get_settings
from app.modules.agent.services import decrypt_secret
from app.modules.knowledge.services import _is_forbidden_ip, validate_fetch_url
from app.shared.exceptions import BadRequestException


async def validate_fetch_target(url: str) -> str:
    validate_fetch_url(url)
    host = httpx.URL(url).host
    addresses = await asyncio.get_running_loop().run_in_executor(
        None, lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    )
    if not addresses or any(_is_forbidden_ip(item[4][0]) for item in addresses):
        raise BadRequestException("fetch target is not public")
    return url


async def fetch_web_text(url: str, *, max_bytes: int, timeout_seconds: int) -> str:
    current_url = url
    async with httpx.AsyncClient(
        timeout=timeout_seconds, follow_redirects=False
    ) as client:
        for _ in range(4):
            await validate_fetch_target(current_url)
            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise BadRequestException("invalid redirect")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise BadRequestException("fetched content is too large")
                return BeautifulSoup(bytes(data), "html.parser").get_text(
                    " ", strip=True
                )
    raise BadRequestException("too many redirects")


def load_file_text(path: str) -> str:
    documents = SimpleDirectoryReader(input_files=[Path(path)]).load_data()
    return "\n\n".join(document.text for document in documents if document.text)


def build_embedding_model(base) -> OpenAIEmbedding:
    api_key = (
        decrypt_secret(base.embedding_api_key_encrypted)
        if base.embedding_api_key_encrypted
        else None
    )
    return OpenAIEmbedding(
        model=base.embedding_model,
        api_base=base.embedding_base_url,
        api_key=api_key,
    )


async def load_document_content(document) -> str:
    if document.source_type == "file" and document.storage_path:
        return await asyncio.to_thread(load_file_text, document.storage_path)
    if document.source_type == "url" and document.source_url:
        settings = get_settings()
        return await fetch_web_text(
            document.source_url,
            max_bytes=settings.agent_max_upload_bytes,
            timeout_seconds=settings.agent_fetch_timeout_seconds,
        )
    raise BadRequestException("document source is invalid")
