"""入站 message_send 契约测试。

本文件原本测的是 ``gateway/schemas.py`` 里的出站协议模型
（``ProtocolEnvelope``/``ErrorPayload`` 等）。那些模型只有测试引用、运行时从不参与
编解码，已在 2026-10-19-sdk-protocol-alignment 中删除；出站形状由
``app.modules.agent_runtime.events`` 的构造器统一生成，其契约锁定在
``tests/gateway/test_event_parity.py``（跨端 golden）与本目录的其他用例里。

这里保留对**入站** payload 的契约测试：它是运行时真正参与校验的部分。
"""

import pytest
from pydantic import ValidationError

from app.modules.gateway.schemas import AttachmentRef, MessageSendPayload


def test_message_send_payload_accepts_wire_field_names():
    payload = MessageSendPayload.model_validate(
        {
            "text": "你好",
            "conversationId": 42,
            "systemPrompt": "以简洁中文回答",
            "thinking": True,
            "futureField": "ignored",
        }
    )

    assert payload.text == "你好"
    assert payload.conversationId == 42
    assert payload.thinking is True
    assert not hasattr(payload, "futureField")


@pytest.mark.parametrize(
    "case",
    [
        {"text": ""},
        {"text": "x" * 20_001},
        {"text": "你好", "conversationId": 0},
        {"text": "你好", "thinking": "maybe"},
    ],
)
def test_message_send_payload_rejects_invalid_input(case):
    with pytest.raises(ValidationError):
        MessageSendPayload.model_validate(case)


def test_message_send_payload_caps_attachments_at_ten():
    refs = [
        AttachmentRef(
            assetId=f"asset_{index}",
            filename=f"file_{index}.pdf",
            mimeType="application/pdf",
            size=100,
        )
        for index in range(11)
    ]

    with pytest.raises(ValidationError):
        MessageSendPayload(text="分析", attachments=refs)


def test_attachment_ref_rejects_unsafe_asset_id():
    with pytest.raises(ValidationError):
        AttachmentRef(
            assetId="../escape",
            filename="report.pdf",
            mimeType="application/pdf",
            size=12345,
        )
