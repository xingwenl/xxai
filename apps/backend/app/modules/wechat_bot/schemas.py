"""微信助手绑定接口数据模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WeChatBotBindingCreate(BaseModel):
    """创建绑定请求：可指定对话智能体（空则用平台默认智能体）。"""

    agent_id: int | None = Field(default=None, description="对话智能体 ID")


class WeChatBotBindingUpdate(BaseModel):
    """更新绑定请求：调整智能体或启停。"""

    agent_id: int | None = Field(default=None, description="对话智能体 ID")
    is_active: bool | None = Field(default=None, description="是否启用")


class WeChatBotBindingRead(BaseModel):
    """绑定记录读取模型（不含敏感字段）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    user_id: int
    agent_id: int | None
    status: str
    ilink_bot_id: str | None
    ilink_user_id: str | None
    last_error: str | None
    last_login_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WeChatBotBindingCreated(BaseModel):
    """创建绑定结果：仅创建时返回一次明文服务 token 与二维码。"""

    binding: WeChatBotBindingRead
    qrcode: str
    api_token: str


class WeChatBotBindingStatusRead(BaseModel):
    """扫码状态轮询结果。"""

    status: str
    message: str
    last_login_at: datetime | None = None


class WeChatBotVerifyCodeRequest(BaseModel):
    """扫码配对码提交请求（need_verifycode 流程）。"""

    verify_code: str = Field(min_length=4, max_length=12, description="微信端显示的配对码")
