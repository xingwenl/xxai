"""用量展示口径：缓存字段归一化、提供方推导与消息元数据往返。

这里钉住三件事：provider 缓存计数（含服务档前缀变体）能进 usage；缺失与 0
不混为一谈；明细写进消息元数据后能原样读回且不受坏数据影响。
"""

from app.modules.agent_runtime.contracts import merge_usage
from app.modules.agent_runtime.langchain_adapter import _normalize_usage
from app.modules.agent_runtime.usage import (
    decorate_usage,
    provider_from_base_url,
    usage_from_message_metadata,
)


def test_normalize_usage_keeps_cache_details_from_langchain_metadata():
    usage = {
        "input_tokens": 120,
        "output_tokens": 8,
        "total_tokens": 128,
        "input_token_details": {"cache_read": 100, "cache_creation": 4},
    }

    assert _normalize_usage(usage) == {
        "prompt_tokens": 120,
        "completion_tokens": 8,
        "total_tokens": 128,
        "cache_read_tokens": 100,
        "cache_creation_tokens": 4,
    }


def test_normalize_usage_sums_service_tier_prefixed_cache_keys():
    usage = {
        "prompt_tokens": 30,
        "completion_tokens": 2,
        "total_tokens": 32,
        "input_token_details": {
            "cache_read": 10,
            "priority_cache_read": 5,
            "flex_cache_read": None,
        },
    }

    assert _normalize_usage(usage)["cache_read_tokens"] == 15


def test_normalize_usage_omits_cache_keys_when_provider_reports_nothing():
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}

    assert _normalize_usage(usage) == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
    }


def test_normalize_usage_reads_openai_and_deepseek_cache_fields():
    openai_shape = {
        "prompt_tokens": 50,
        "completion_tokens": 3,
        "total_tokens": 53,
        "prompt_tokens_details": {"cached_tokens": 30},
    }
    deepseek_shape = {
        "prompt_tokens": 20,
        "completion_tokens": 3,
        "total_tokens": 23,
        "prompt_cache_hit_tokens": 7,
    }

    assert _normalize_usage(openai_shape)["cache_read_tokens"] == 30
    assert _normalize_usage(deepseek_shape)["cache_read_tokens"] == 7


def test_merge_usage_sums_cache_tokens_across_turns():
    merged = merge_usage(
        {
            "prompt_tokens": 10,
            "completion_tokens": 1,
            "total_tokens": 11,
            "cache_read_tokens": 6,
        },
        {
            "prompt_tokens": 5,
            "completion_tokens": 1,
            "total_tokens": 6,
            "cache_read_tokens": 2,
        },
    )

    assert merged == {
        "prompt_tokens": 15,
        "completion_tokens": 2,
        "total_tokens": 17,
        "cache_read_tokens": 8,
    }


def test_decorate_usage_derives_total_and_attaches_model_provider():
    assert decorate_usage(
        {"prompt_tokens": 12, "completion_tokens": 5},
        model="deepseek-v4.1-flash",
        provider="deepseek",
    ) == {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
        "model": "deepseek-v4.1-flash",
        "provider": "deepseek",
    }


def test_decorate_usage_rejects_unusable_payloads():
    assert decorate_usage(None) is None
    assert decorate_usage("oops") is None
    assert decorate_usage({"prompt_tokens": True, "completion_tokens": 1}) is None
    assert decorate_usage({"prompt_tokens": -1, "completion_tokens": 1}) is None
    # 只有 output 没有 input 时无法推导总量，宁可不渲染。
    assert decorate_usage({"completion_tokens": 1}) is None


def test_decorate_usage_keeps_already_normalized_cache_tokens():
    """已归一化的字典再走一遍装饰（事件透传、元数据往返）不能丢缓存计数。"""

    assert decorate_usage({"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11, "cache_read_tokens": 7}) == {
        "prompt_tokens": 10,
        "completion_tokens": 1,
        "total_tokens": 11,
        "cache_read_tokens": 7,
    }


def test_usage_from_message_metadata_whitelists_keys_and_survives_bad_data():
    metadata = {
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
            "model": "m",
            "junk": "should-drop",
        }
    }

    assert usage_from_message_metadata(metadata) == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
        "model": "m",
    }
    assert usage_from_message_metadata(None) is None
    assert usage_from_message_metadata({}) is None
    assert usage_from_message_metadata({"usage": "oops"}) is None
    assert usage_from_message_metadata({"usage": {"prompt_tokens": "12"}}) is None


def test_provider_from_base_url_reads_host_label():
    assert provider_from_base_url("https://api.deepseek.com/v1") == "deepseek"
    assert provider_from_base_url("api.deepseek.com") == "deepseek"
    assert provider_from_base_url("https://api.openai.com/v1") == "openai"
    assert provider_from_base_url("http://localhost:8000/v1") == "localhost"
    assert provider_from_base_url("http://192.168.1.10:8000/v1") == "192.168.1.10"
    assert provider_from_base_url("https://ai-base.local/v1") == "ai-base"
    assert provider_from_base_url(None) is None
    assert provider_from_base_url("   ") is None
