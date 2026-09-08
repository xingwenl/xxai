"""AgentRuntime 模型错误降级恢复器的定向测试。

覆盖上下文超限降级与纯文本模型拒图降级两条恢复策略的判定与产出，确保
三协议灰度路径把 legacy 的真实模型缓解迁入 AgentLoop 后行为一致。
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.modules.conversation.runtime import (
    make_context_degrade_recoverer,
    make_multimodal_degrade_recoverer,
)


def _context_length_error():
    return RuntimeError("Request too large, code: context_length_exceeded")


def _image_error():
    return RuntimeError(
        "messages.content.type: 'image_url' is not supported, only 'text'"
    )


def _image_messages():
    return [
        SystemMessage(content="系统提示"),
        HumanMessage(
            content=[
                {"type": "text", "text": "请描述这张图"},
                {"type": "text", "text": "document 摘要"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,xxx"},
                },
            ]
        ),
    ]


def test_context_degrade_recoverer_returns_system_and_user_only():
    recover = make_context_degrade_recoverer("系统提示", "用户提问")
    recovered = recover(_context_length_error(), [])
    assert recovered is not None
    assert len(recovered) == 2
    assert isinstance(recovered[0], SystemMessage)
    assert isinstance(recovered[1], HumanMessage)
    assert recovered[1].content.startswith("用户提问")
    assert "上下文上限" in recovered[1].content
    # 非超限错误不重试。
    assert recover(RuntimeError("boom"), []) is None


def test_multimodal_recoverer_strips_images_on_reject_keeps_text_and_doc():
    recover = make_multimodal_degrade_recoverer("系统提示", "用户提问")
    messages = _image_messages()
    recovered = recover(_image_error(), messages)
    assert recovered is not None
    assert len(recovered) == 2
    user_content = recovered[1].content
    types = [part.get("type") for part in user_content]
    assert "image_url" not in types
    assert types == ["text", "text"]


def test_multimodal_recoverer_also_handles_context_limit():
    recover = make_multimodal_degrade_recoverer("系统提示", "用户提问")
    recovered = recover(_context_length_error(), _image_messages())
    assert recovered is not None
    assert recovered[-1].content.startswith("用户提问")
    assert recover(RuntimeError("other"), _image_messages()) is None
