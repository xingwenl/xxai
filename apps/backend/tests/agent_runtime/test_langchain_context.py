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
