import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.modules.agent.repositories import AgentRepository
from app.modules.agent.schemas import AgentCreate, AgentUpdate, AgentVersionCreate
from app.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)


def _fernet(master_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(master_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str, *, master_key: str | None = None) -> str:
    secret = master_key or get_settings().agent_master_key
    return _fernet(secret).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str, *, master_key: str | None = None) -> str:
    secret = master_key or get_settings().agent_master_key
    try:
        return _fernet(secret).decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise BadRequestException("unable to decrypt secret") from exc


async def create_agent(
    repo: AgentRepository, payload: AgentCreate, *, platform_id: int
):
    if await repo.get_by_slug(platform_id, payload.slug) is not None:
        raise ConflictException("agent slug already exists")
    return await repo.create_agent(payload, platform_id)


async def create_agent_version(
    repo: AgentRepository,
    agent_id: int,
    payload: AgentVersionCreate,
    *,
    platform_id: int,
):
    if await repo.get_agent(agent_id, platform_id) is None:
        raise NotFoundException("agent not found")
    encrypted_payload = payload
    if payload.api_key:
        encrypted_payload = payload.model_copy(
            update={"api_key": encrypt_secret(payload.api_key)}
        )
    return await repo.create_version(agent_id, encrypted_payload)


async def update_agent(
    repo: AgentRepository,
    agent_id: int,
    payload: AgentUpdate,
    *,
    platform_id: int,
):
    agent = await repo.get_agent(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    if payload.slug is not None and payload.slug != agent.slug:
        existing = await repo.get_by_slug(platform_id, payload.slug)
        if existing is not None and existing.id != agent_id:
            raise ConflictException("agent slug already exists")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise BadRequestException("no fields to update")
    return await repo.update_agent(agent, payload)


async def delete_agent(repo: AgentRepository, agent_id: int, *, platform_id: int) -> None:
    agent = await repo.get_agent(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    await repo.delete_agent(agent)


async def publish_agent_version(
    repo: AgentRepository, agent_id: int, version_id: int, *, platform_id: int
):
    agent = await repo.get_agent(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    try:
        return await repo.publish_version(agent, version_id)
    except LookupError as exc:
        raise NotFoundException("agent version not found") from exc


async def rollback_agent(
    repo: AgentRepository, agent_id: int, version_id: int, *, platform_id: int
):
    agent = await repo.get_agent(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    try:
        return await repo.rollback(agent, version_id)
    except LookupError as exc:
        raise NotFoundException("agent version not found") from exc


def build_chat_model(version) -> ChatOpenAI:
    settings = get_settings()
    api_key = (
        decrypt_secret(version.api_key_encrypted) if version.api_key_encrypted else None
    )
    # 默认关闭 SDK 自动重试，确保上游 502/连接异常能在本轮超时前进入统一 error 事件。
    model_options = {
        "timeout": settings.model_request_timeout_seconds,
        "stream_chunk_timeout": settings.model_request_timeout_seconds,
        "max_retries": settings.model_max_retries,
        **(version.model_options or {}),
    }
    return ChatOpenAI(
        model=version.model_name or settings.model_default_name,
        base_url=version.model_base_url or settings.model_default_base_url,
        api_key=api_key,
        temperature=version.temperature,
        **model_options,
    )
