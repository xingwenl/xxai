from langchain_core.messages import AIMessageChunk

from app.modules.agent.services import ProviderThinkingChatOpenAI, _thinking_extra


def test_thinking_extra_normalizes_provider_fields():
    assert _thinking_extra({"reasoning_content": "先分析"}) == {
        "reasoning_content": "先分析"
    }
    assert _thinking_extra({"reasoning": "再推理"}) == {"reasoning": "再推理"}
    assert _thinking_extra(
        {"reasoning_details": [{"text": "细节一"}, {"content": "细节二"}]}
    ) == {"reasoning_details": "细节一细节二"}
    assert _thinking_extra({"content": "正文"}) == {}


def test_streaming_chunk_keeps_reasoning_content():
    model = ProviderThinkingChatOpenAI(model="deepseek-reasoner", api_key="test-key")
    chunk = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "deepseek-reasoner",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "reasoning_content": "先分析问题",
                },
                "finish_reason": None,
            }
        ],
    }

    generation_chunk = model._convert_chunk_to_generation_chunk(
        chunk, AIMessageChunk, None
    )

    assert generation_chunk is not None
    assert generation_chunk.message.content == ""
    assert (
        generation_chunk.message.additional_kwargs["reasoning_content"] == "先分析问题"
    )


def test_streaming_chunk_keeps_content_untouched():
    model = ProviderThinkingChatOpenAI(model="deepseek-reasoner", api_key="test-key")
    chunk = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "deepseek-reasoner",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "最终回答"},
                "finish_reason": None,
            }
        ],
    }

    generation_chunk = model._convert_chunk_to_generation_chunk(
        chunk, AIMessageChunk, None
    )

    assert generation_chunk is not None
    assert generation_chunk.message.content == "最终回答"
    assert generation_chunk.message.additional_kwargs == {}


def test_non_streaming_response_keeps_reasoning_content():
    model = ProviderThinkingChatOpenAI(model="deepseek-reasoner", api_key="test-key")
    response = {
        "id": "chatcmpl-2",
        "object": "chat.completion",
        "created": 1,
        "model": "deepseek-reasoner",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "最终回答",
                    "reasoning_content": "完整思考",
                },
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    }

    result = model._create_chat_result(response)

    message = result.generations[0].message
    assert message.content == "最终回答"
    assert message.additional_kwargs["reasoning_content"] == "完整思考"
