from app.modules.agent_runtime.langchain_adapter import build_langchain_messages


def test_build_langchain_messages_keeps_order_and_attachment_parts():
    messages = build_langchain_messages(
        system_prompt="系统",
        history=[],
        user_message="问题",
        document_text_parts=[{"type": "text", "text": "文档"}],
    )

    assert [type(item).__name__ for item in messages] == [
        "SystemMessage",
        "HumanMessage",
    ]
    assert messages[-1].content[0]["text"] == "问题"
    assert messages[-1].content[1]["text"] == "文档"


def test_build_langchain_messages_user_content_orders_document_before_image():
    messages = build_langchain_messages(
        system_prompt="识别图片",
        user_message="这是什么",
        document_text_parts=[{"type": "text", "text": "附件内容"}],
        image_parts=[
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,YQ=="}}
        ],
    )

    user_content = messages[-1].content
    assert [part["type"] for part in user_content] == ["text", "text", "image_url"]
    assert user_content[0]["text"] == "这是什么"
    assert user_content[1]["text"] == "附件内容"
    assert user_content[2]["image_url"]["url"].startswith("data:image/jpeg")


def test_build_langchain_messages_without_extra_parts_keeps_plain_text():
    messages = build_langchain_messages(
        system_prompt="系统",
        user_message="纯文本问题",
    )

    assert messages[-1].content == "纯文本问题"
