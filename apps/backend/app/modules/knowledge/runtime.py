import asyncio
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from app.core.logging import get_logger
from llama_index.core import SimpleDirectoryReader
from llama_index.embeddings.openai import OpenAIEmbedding, OpenAIEmbeddingModelType

from app.core.config import get_settings
from app.modules.agent.services import decrypt_secret
from app.modules.knowledge.services import _is_forbidden_ip, validate_fetch_url
from app.shared.exceptions import BadRequestException

logger = get_logger(__name__)
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


def resolve_storage_path(path: str, storage_root: str | Path | None = None) -> Path:
    candidate = Path(path)
    if candidate.exists():
        return candidate

    root = Path(storage_root or get_settings().agent_file_storage_path)
    if not candidate.is_absolute():
        return root / candidate

    parts = candidate.parts
    if "storage" in parts:
        # 本地 API 与容器 Worker 混跑时，数据库里可能保留主机绝对路径；
        # Worker 需按当前环境的存储根目录重定位到同一份挂载文件。
        storage_index = len(parts) - 1 - list(reversed(parts)).index("storage")
        relative_path = Path(*parts[storage_index + 1 :])
        return root / relative_path

    return candidate


def load_file_text(path: str) -> str:
    documents = SimpleDirectoryReader(
        input_files=[resolve_storage_path(path)]
    ).load_data()
    return "\n\n".join(document.text for document in documents if document.text)


def _is_local_embedding_endpoint(base_url: str | None) -> bool:
    if not base_url:
        return False
    hostname = urlparse(base_url).hostname
    return hostname in {"localhost", "127.0.0.1", "::1", "ollama"}


def _uses_custom_embedding_model_name(model: str) -> bool:
    return model not in {item.value for item in OpenAIEmbeddingModelType}


def build_embedding_model(base) -> OpenAIEmbedding:
    api_key = (
        decrypt_secret(base.embedding_api_key_encrypted)
        if base.embedding_api_key_encrypted
        else "ollama" if _is_local_embedding_endpoint(base.embedding_base_url) else None
    )
    # OpenAIEmbedding 默认 embed_batch_size=100，而部分 OpenAI 兼容服务
    # （如 Gemini 风格网关）单次请求最多接受 10 条 input.contents，
    # 超过会返回 400 批次超限错误；这里统一收口为可配置的批次上限。
    embed_batch_size = get_settings().embedding_batch_size
    logger.info(
        "Using embedding model config model=%s base_url=%s has_api_key=%s",
        base.embedding_model,
        base.embedding_base_url,
        bool(api_key),
    )

    if _uses_custom_embedding_model_name(base.embedding_model):
        # LlamaIndex 会校验 model 参数是否属于 OpenAI 枚举；model_name
        # 允许将第三方 OpenAI-compatible 服务的实际模型名原样放入请求体。
        return OpenAIEmbedding(
            model="text-embedding-3-small",
            model_name=base.embedding_model,
            api_base=base.embedding_base_url,
            api_key=api_key,
            embed_batch_size=embed_batch_size,
        )
    return OpenAIEmbedding(
        model=base.embedding_model,
        api_base=base.embedding_base_url,
        api_key=api_key,
        embed_batch_size=embed_batch_size,
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
