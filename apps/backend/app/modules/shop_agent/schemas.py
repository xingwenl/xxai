"""店铺运营平台（hua8）智能体会话接口的请求契约。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ShopAgentSessionRequest(BaseModel):
    """浏览器登录店铺系统后提交的会话数据。"""

    model_config = ConfigDict(populate_by_name=True)

    shop_token: str = Field(
        alias="shopToken",
        min_length=1,
        max_length=8192,
        description="店铺系统登录 access_token",
    )
    shop_user_id: str = Field(
        alias="shopUserId",
        min_length=1,
        max_length=255,
        description="店铺系统用户 ID（external_user_id）",
    )
    agent_id: int | None = Field(
        alias="agentId",
        default=None,
        ge=1,
        description="目标 Agent ID；缺省时沿用服务端配置的默认 Agent",
    )
    host_tool_names: list[str] = Field(
        alias="hostToolNames",
        default_factory=list,
        max_length=100,
        description="页面宿主工具候选名；实际生效集合还需与 Embed Client 绑定工具取交集",
    )
    client_id: str | None = Field(
        alias="clientId",
        default=None,
        min_length=1,
        max_length=80,
        description="调用方自带的 Embed Client ID；缺省时沿用服务端配置的 Client",
    )
    client_secret: str | None = Field(
        alias="clientSecret",
        default=None,
        min_length=1,
        max_length=256,
        description="调用方自带的 Embed Client 密钥；必须与其他字段同时提供，且只能由服务端持有",
    )
