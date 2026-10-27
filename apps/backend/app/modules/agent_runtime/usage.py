"""模型用量的展示口径：归一化、提供方推导与消息元数据读写。

这里的「用量」是**按消息展示**的附属数据，不是计费事实——计费事实仍在
``model_usage_records``。展示数据跟消息一起存（``message_metadata["usage"]``），
好处是历史回放、实时事件与快照三处读到的永远是同一份自包含明细，后续模型
配置变化也不会让旧消息的显示漂移。

缓存字段的缺失与 0 是两件事：provider 没报缓存计数时**不产出该键**，上层据此
隐藏「缓存命中」行；报了 0 则照实显示 0%。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# 消息元数据里承载用量明细的键；与 tool snapshots 并列存放。
USAGE_METADATA_KEY = "usage"

_PROMPT_KEYS = ("prompt_tokens", "input_tokens")
_COMPLETION_KEYS = ("completion_tokens", "output_tokens")
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_MULTI_LABEL_SUFFIXES = {"com", "net", "org", "cn", "io", "co", "dev", "local"}


def _non_negative_int(value: Any) -> int | None:
    """只接受真正的非负整数；``bool`` 虽是 int 子类但语义上是标志位。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_int(source: dict, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _non_negative_int(source.get(key))
        if value is not None:
            return value
    return None


def _detail_sum(details: Any, suffix: str) -> int | None:
    """累计 ``cache_read`` 及其服务档前缀变体（``priority_cache_read`` 等）。

    langchain-openai 在 priority/flex 服务档下会把键写成 ``priority_cache_read``
    （见 langchain_openai 1.4.1 ``chat_models/base.py`` 的 ``_create_usage_metadata``），
    展示时这些键应当合并成同一个缓存计数。
    """
    if not isinstance(details, dict):
        return None
    total: int | None = None
    for key, value in details.items():
        if not isinstance(key, str):
            continue
        if key != suffix and not key.endswith(f"_{suffix}"):
            continue
        amount = _non_negative_int(value)
        if amount is None:
            continue
        total = (total or 0) + amount
    return total


def normalize_cache_tokens(usage: Any) -> dict[str, int]:
    """从一次模型调用的 usage 里提取缓存计数（读不到就不产出对应键）。"""
    if not isinstance(usage, dict):
        return {}
    input_details = usage.get("input_token_details")
    cache_read = _detail_sum(input_details, "cache_read")
    cache_creation = _detail_sum(input_details, "cache_creation")
    if cache_read is None:
        # OpenAI 兼容的原始响应：prompt_tokens_details.cached_tokens。
        cache_read = _detail_sum(usage.get("prompt_tokens_details"), "cached_tokens")
    if cache_read is None:
        # DeepSeek 原生 KV cache 字段。
        cache_read = _non_negative_int(usage.get("prompt_cache_hit_tokens"))
    if cache_creation is None:
        cache_creation = _non_negative_int(usage.get("cache_creation_input_tokens"))
    # 已经归一化过的字典（消息元数据往返、事件透传）要能原样读回。
    if cache_read is None:
        cache_read = _non_negative_int(usage.get("cache_read_tokens"))
    if cache_creation is None:
        cache_creation = _non_negative_int(usage.get("cache_creation_tokens"))
    tokens: dict[str, int] = {}
    if cache_read is not None:
        tokens["cache_read_tokens"] = cache_read
    if cache_creation is not None:
        tokens["cache_creation_tokens"] = cache_creation
    return tokens


def decorate_usage(
    usage: Any,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> dict[str, Any] | None:
    """把任意 provider 的用量字典收敛成展示用明细。

    缺少 prompt/completion/total 中任一可推导值时返回 ``None``：与其显示一份
    残缺明细，不如让前端不渲染 chip。
    """
    if not isinstance(usage, dict):
        return None
    prompt = _first_int(usage, _PROMPT_KEYS)
    completion = _first_int(usage, _COMPLETION_KEYS)
    total = _non_negative_int(usage.get("total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    if prompt is None or completion is None or total is None:
        return None
    payload: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    payload.update(normalize_cache_tokens(usage))
    resolved_model = _clean_text(model) or _clean_text(usage.get("model"))
    resolved_provider = _clean_text(provider) or _clean_text(usage.get("provider"))
    if resolved_model:
        payload["model"] = resolved_model
    if resolved_provider:
        payload["provider"] = resolved_provider
    return payload


def usage_from_message_metadata(metadata: Any) -> dict[str, Any] | None:
    """从消息元数据里读回用量明细；坏数据返回 ``None``，不让快照整体 500。"""
    if not isinstance(metadata, dict):
        return None
    return decorate_usage(metadata.get(USAGE_METADATA_KEY))


def provider_from_base_url(base_url: str | None) -> str | None:
    """按 base_url 的主机名推导提供方标识（``api.deepseek.com`` → ``deepseek``）。

    注册表里没有独立的「提供方」字段，而明细卡要显示「提供方/模型」；这里只做
    诚实的轻量推导：取主机名的主体标签，IP/本机地址原样返回，取不到返回 ``None``
    由前端隐藏该行。
    """
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    candidate = base_url.strip()
    host = urlparse(candidate).hostname
    if not host:
        host = urlparse(f"//{candidate}").hostname
    if not host:
        return None
    host = host.lower()
    if _IPV4_RE.match(host):
        return host
    labels = [label for label in host.split(".") if label]
    if not labels:
        return None
    if len(labels) >= 3 and labels[-2] in _MULTI_LABEL_SUFFIXES:
        return labels[-3]
    if len(labels) >= 2:
        return labels[-2]
    return labels[0]
