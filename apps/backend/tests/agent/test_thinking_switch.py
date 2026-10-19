"""请求级思考开关到上游模型参数的翻译与构造行为。"""

from dataclasses import dataclass, field
from typing import Any

from app.modules.agent.services import _resolve_thinking_options, build_chat_model
from app.modules.model_registry.resolver import ResolvedModel


@dataclass
class _Version:
    """伪造 AgentVersion，只提供 build_chat_model 读取的字段。"""

    temperature: float = 0.2
    model_options: dict[str, Any] = field(default_factory=dict)


def _resolved(model_name: str = "deepseek-v4-flash") -> ResolvedModel:
    """模型三要素由注册表解析结果提供，版本行不再承载。"""
    return ResolvedModel(
        model_name=model_name,
        base_url=None,
        api_key="sk-test",
        capabilities=None,
        options={},
    )


def test_deepseek_fallback_sends_explicit_switch():
    """DeepSeek 上游默认 enabled，因此关闭必须显式下发 disabled。"""
    assert _resolve_thinking_options(
        {}, model_name="deepseek-v4-flash", thinking=False
    ) == {"extra_body": {"thinking": {"type": "disabled"}}}
    assert _resolve_thinking_options(
        {}, model_name="deepseek-v4-flash", thinking=True
    ) == {"extra_body": {"thinking": {"type": "enabled"}}}


def test_unknown_provider_falls_back_to_reasoning_effort():
    """非 DeepSeek 厂商关闭时用通用参数；开启时不注入，沿用厂商默认。"""
    assert _resolve_thinking_options({}, model_name="gpt-4o", thinking=False) == {
        "reasoning_effort": "none"
    }
    assert _resolve_thinking_options({}, model_name="gpt-4o", thinking=True) == {}


def test_explicit_model_options_mapping_wins():
    """接入方显式配置的映射优先于模型名兜底。"""
    mapping = {
        "thinking": {
            "on": {"extra_body": {"enable_thinking": True}},
            "off": {"extra_body": {"enable_thinking": False}},
        }
    }

    assert _resolve_thinking_options(
        mapping, model_name="qwen3", thinking=False
    ) == {"extra_body": {"enable_thinking": False}}
    # 即便模型名命中 deepseek，显式映射也应覆盖兜底行为。
    assert _resolve_thinking_options(
        mapping, model_name="deepseek-v4-flash", thinking=True
    ) == {"extra_body": {"enable_thinking": True}}


def test_mapping_without_matching_side_falls_back():
    """映射只配了一半时，未配置的一侧回落到模型名兜底。"""
    mapping = {"thinking": {"off": {"extra_body": {"enable_thinking": False}}}}

    assert _resolve_thinking_options(
        mapping, model_name="deepseek-v4-flash", thinking=True
    ) == {"extra_body": {"thinking": {"type": "enabled"}}}


def test_thinking_not_passed_keeps_legacy_behaviour():
    """不传 thinking 时构造参数与改动前一致：无 extra_body / reasoning_effort。"""
    model = build_chat_model(_Version(), resolved=_resolved())
    payload = model._default_params

    assert "reasoning_effort" not in payload or payload["reasoning_effort"] is None
    assert "extra_body" not in payload or payload["extra_body"] is None


def test_thinking_false_injects_disabled_for_deepseek():
    model = build_chat_model(_Version(), resolved=_resolved(), thinking=False)
    payload = model._default_params

    assert payload["extra_body"] == {"thinking": {"type": "disabled"}}


def test_thinking_true_injects_enabled_for_deepseek():
    model = build_chat_model(_Version(), resolved=_resolved(), thinking=True)
    payload = model._default_params

    assert payload["extra_body"] == {"thinking": {"type": "enabled"}}


def test_thinking_mapping_key_never_leaks_to_client():
    """model_options 里的 thinking 映射是我们的约定，不能传给 ChatOpenAI。"""
    model = build_chat_model(
        _Version(
            model_options={
                "thinking": {"off": {"extra_body": {"enable_thinking": False}}}
            }
        ),
        resolved=_resolved(),
        thinking=None,
    )

    # 未传请求级开关时不注入，且映射键不会变成构造器未知参数。
    assert model._default_params.get("extra_body") is None


def test_extra_body_merges_with_existing_options():
    """思考开关注入 extra_body 时不能覆盖接入方已有的其他厂商参数。"""
    model = build_chat_model(
        _Version(model_options={"extra_body": {"ttl": 300}}),
        resolved=_resolved(),
        thinking=False,
    )

    assert model._default_params["extra_body"] == {
        "ttl": 300,
        "thinking": {"type": "disabled"},
    }
