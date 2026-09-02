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
