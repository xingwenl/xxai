"""网关**入站**消息 schema（``message_send`` 的 payload 与附件引用）。

出站协议事件不在这里定义：全部由
``app.modules.agent_runtime.events`` 的构造器生成信封字典，再经 ``to_wire``
统一转成 camelCase 线协议。此前这里另存了一套出站 Pydantic 模型
（``ProtocolEnvelope``/``ProtocolPayload``/``ErrorPayload`` 等），但它们只有测试
引用、运行时从不参与编解码——两套形状必然漂移（例如 ``confirmation_required``
的 ``sideEffect``/``expiresAt`` 只在其中一套里），因此本轮删除，只保留真正
参与入站校验的模型。
"""

import re

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# 附件引用 schema（message_send 入站消息中的 attachments 字段）
# ---------------------------------------------------------------------------

_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_MAX_ATTACHMENTS = 10


class AttachmentRef(BaseModel):
    """消息发送时携带的附件引用，客户端只传元数据，后端重新校验。"""

    assetId: str = Field(
        min_length=1,
        max_length=128,
        description="附件唯一标识，由上传接口返回",
    )
    filename: str = Field(
        min_length=1,
        max_length=255,
        description="安全化处理后的文件名",
    )
    mimeType: str = Field(
        min_length=1,
        max_length=255,
        description="资源媒体类型",
    )
    size: int = Field(
        ge=1,
        description="资源字节大小",
    )

    @field_validator("assetId")
    @classmethod
    def validate_asset_id_format(cls, value: str) -> str:
        if not _ASSET_ID_RE.fullmatch(value):
            raise ValueError("assetId 格式无效")
        return value


class MessageSendPayload(BaseModel):
    """message_send 入站消息的 payload 结构。"""

    text: str = Field(
        min_length=1,
        max_length=20_000,
        description="用户消息文本",
    )
    conversationId: int | None = Field(
        default=None,
        ge=1,
        description="会话 ID",
    )
    attachments: list[AttachmentRef] | None = Field(
        default=None,
        max_length=_MAX_ATTACHMENTS,
        description="附件引用列表，最多 10 个",
    )
    systemPrompt: str | None = Field(
        default=None,
        max_length=20_000,
        description="可选的系统提示词",
    )
    thinking: bool | None = Field(
        default=None,
        description=(
            "请求级思考开关：true 进入思考模式，false 关闭，"
            "不传表示不干预（沿用模型与厂商默认）"
        ),
    )
