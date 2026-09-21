import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from langchain_openai import ChatOpenAI
from pydantic import Field

from app.core.config import get_settings
from app.modules.agent.provider_headers import (
    SessionIdProvider,
    is_opencode_endpoint,
    merge_default_headers,
    resolve_session_id,
    session_headers,
)
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


async def delete_agent(
    repo: AgentRepository, agent_id: int, *, platform_id: int
) -> None:
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


_THINKING_FIELDS = ("reasoning_content", "reasoning", "reasoning_details")


def _thinking_extra(raw: dict[str, Any]) -> dict[str, Any]:
    """从 OpenAI 兼容响应的 delta/message 中提取厂商私有思考字段。

    DeepSeek/GLM/Kimi 等思考模型会在流式 delta 或完整 message 里返回
    reasoning_content 等非 OpenAI 规范字段；这里统一归一为字符串后补回
    additional_kwargs，避免思考内容在 LangChain 解析阶段被丢弃。
    """
    extra: dict[str, Any] = {}
    for key in _THINKING_FIELDS:
        value = raw.get(key)
        if isinstance(value, str):
            if value:
                extra[key] = value
            continue
        if isinstance(value, list):
            text = "".join(
                (
                    item.get("text") or item.get("content") or ""
                    if isinstance(item, dict)
                    else str(item)
                )
                for item in value
            )
            if text:
                extra[key] = text
    return extra


class ProviderThinkingChatOpenAI(ChatOpenAI):
    """保留 OpenAI 兼容厂商思考字段的 ChatOpenAI 子类。

    langchain-openai 只按官方 OpenAI 规范解析响应，会丢弃 DeepSeek/GLM 等厂商
    在流式 delta 或完整 message 中返回的 reasoning_content。该子类在标准解析
    结果上把这些字段补回 additional_kwargs，供 stream_graph 实时提取并落库。

    同时负责按次注入 OpenCode 兼容的会话头：会话 id 必须在每次请求时求值，
    因此在调用期（而不是客户端构造期）写入 ``extra_headers``。
    """

    # 无参可调用对象，返回当前请求的会话 id；非 OpenCode 端点不会用到。
    # 排除序列化与 repr：可调用对象不可 JSON 序列化，避免污染日志与追踪链路。
    session_id_provider: Any = Field(default=None, exclude=True, repr=False)

    def _with_session_headers(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """在 kwargs 中补上 OpenCode 会话头；不适用时原样返回。"""

        base_url = self.openai_api_base
        if not is_opencode_endpoint(base_url):
            return kwargs
        extra = session_headers(
            base_url,
            resolve_session_id(self.session_id_provider),
            configured=self.default_headers,
        )
        if not extra:
            return kwargs
        # 调用方已给出的 per-call header 优先，避免覆盖上层显式意图。
        kwargs["extra_headers"] = {**extra, **(kwargs.get("extra_headers") or {})}
        return kwargs

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **self._with_session_headers(kwargs),
        )

    # 基类的 _stream/_astream 使用 (*args, **kwargs) 签名，这里保持同样形式，
    # 避免破坏以位置参数调用 stop/run_manager 的场景。
    def _stream(self, *args: Any, **kwargs: Any):
        return super()._stream(*args, **self._with_session_headers(kwargs))

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        return await super()._agenerate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **self._with_session_headers(kwargs),
        )

    async def _astream(self, *args: Any, **kwargs: Any):
        async for chunk in super()._astream(
            *args, **self._with_session_headers(kwargs)
        ):
            yield chunk

    def _convert_chunk_to_generation_chunk(
        self, chunk, default_chunk_class, base_generation_info
    ):
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None
        choices = chunk.get("choices") or []
        if choices:
            extra = _thinking_extra(choices[0].get("delta") or {})
            if extra:
                message = generation_chunk.message
                message.additional_kwargs = {
                    **message.additional_kwargs,
                    **extra,
                }
        return generation_chunk

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(warnings=False)
        )
        choices = response_dict.get("choices") or []
        for index, choice in enumerate(choices):
            if index >= len(result.generations):
                break
            extra = _thinking_extra(choice.get("message") or {})
            if extra:
                message = result.generations[index].message
                message.additional_kwargs = {
                    **message.additional_kwargs,
                    **extra,
                }
        return result


# model_options 中保留的思考开关映射键，形如
# {"thinking": {"on": {...}, "off": {...}}}；它只服务请求级开关翻译，
# 不能透传给 ChatOpenAI 构造器（未知关键字会直接抛错）。
_THINKING_OPTION_KEY = "thinking"


def _resolve_thinking_options(
    raw_options: dict[str, Any], *, model_name: str, thinking: bool
) -> dict[str, Any]:
    """把请求级布尔开关翻译为该模型可直接接受的上游参数。

    翻译优先级：
    1. ``model_options["thinking"]["on"|"off"]``：接入方显式给出的参数对象，
       原样采用（键名即 ChatOpenAI 关键字，如 ``extra_body`` / ``reasoning_effort``）。
    2. 模型名兜底：DeepSeek 用顶层 ``thinking.type``；其余厂商关闭时用
       ``reasoning_effort="none"``，开启时不注入（沿用厂商自身默认）。

    注：DeepSeek 的 ``thinking`` 上游默认是 ``enabled``，因此「关闭」必须显式下发
    ``disabled``，不能靠省略字段实现。
    """
    mapping = raw_options.get(_THINKING_OPTION_KEY)
    if isinstance(mapping, dict):
        selected = mapping.get("on" if thinking else "off")
        if isinstance(selected, dict):
            return dict(selected)
    if "deepseek" in model_name.lower():
        return {
            "extra_body": {
                "thinking": {"type": "enabled" if thinking else "disabled"}
            }
        }
    # 无法识别厂商时静默降级：开启不注入，关闭尝试通用参数；
    # 厂商不吃该参数时请求仍能成功，只是思考未被关闭。
    return {} if thinking else {"reasoning_effort": "none"}


def build_chat_model(
    version,
    *,
    session_id_provider: SessionIdProvider | None = None,
    thinking: bool | None = None,
) -> ChatOpenAI:
    """按 Agent 版本构造 ChatOpenAI 客户端。

    ``session_id_provider`` 为可选的会话 id 惰性求值入口，用于 OpenCode 兼容头；
    非 OpenCode 端点不会产生任何额外请求头。

    ``thinking`` 为请求级思考开关：``None`` 表示不干预（与既有行为完全一致），
    ``True`` / ``False`` 则按 :func:`_resolve_thinking_options` 注入上游参数。
    """

    settings = get_settings()
    api_key = (
        decrypt_secret(version.api_key_encrypted) if version.api_key_encrypted else None
    )
    base_url = version.model_base_url or settings.model_default_base_url
    model_name = version.model_name or settings.model_default_name
    # default_headers 单独取出后再合并，避免直接展开时与兼容头互相覆盖。
    raw_options = dict(version.model_options or {})
    configured_headers = raw_options.pop("default_headers", None)
    # 思考映射是我们的配置约定，必须剥离，否则会被当成 ChatOpenAI 未知参数。
    raw_options.pop(_THINKING_OPTION_KEY, None)
    # 默认关闭 SDK 自动重试，确保上游 502/连接异常能在本轮超时前进入统一 error 事件。
    model_options: dict[str, Any] = {
        "timeout": settings.model_request_timeout_seconds,
        "stream_chunk_timeout": settings.model_request_timeout_seconds,
        "max_retries": settings.model_max_retries,
        **raw_options,
        "default_headers": merge_default_headers(base_url, configured_headers),
    }
    if thinking is not None:
        thinking_options = _resolve_thinking_options(
            dict(version.model_options or {}),
            model_name=model_name,
            thinking=thinking,
        )
        # extra_body 需要与既有配置深合并，避免思考开关覆盖掉接入方
        # 已配置的其他厂商参数（如 ttl、use_beam_search）。
        incoming_extra = thinking_options.pop("extra_body", None)
        if isinstance(incoming_extra, dict):
            existing_extra = model_options.get("extra_body")
            merged_extra = (
                {**existing_extra, **incoming_extra}
                if isinstance(existing_extra, dict)
                else incoming_extra
            )
            model_options["extra_body"] = merged_extra
        model_options.update(thinking_options)
    return ProviderThinkingChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=version.temperature,
        session_id_provider=session_id_provider,
        **model_options,
    )
