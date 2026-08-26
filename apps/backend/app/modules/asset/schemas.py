"""Asset 上传和状态查询的 Pydantic schema。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AssetStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"
    unsupported = "unsupported"


class AssetUploadResponse(BaseModel):
    """上传成功后的响应。"""

    assetId: str = Field(description="对外不可枚举的资源标识")
    filename: str = Field(description="安全化处理后的文件名")
    mimeType: str = Field(description="资源媒体类型")
    size: int = Field(description="资源字节大小")
    status: AssetStatus = Field(description="当前处理状态")
    createdAt: datetime = Field(description="创建时间")


class AssetStatusResponse(BaseModel):
    """附件状态查询响应。"""

    assetId: str = Field(description="资源标识")
    filename: str = Field(description="文件名")
    mimeType: str = Field(description="资源媒体类型")
    size: int = Field(description="资源字节大小")
    status: AssetStatus = Field(description="当前处理状态")
    errorMessage: str | None = Field(default=None, description="失败时的错误信息")
    chunks: list[AssetChunkRead] = Field(default_factory=list, description="已解析的文本切块")
    createdAt: datetime = Field(description="创建时间")
    completedAt: datetime | None = Field(default=None, description="处理完成时间")


class AssetChunkRead(BaseModel):
    """切块只读视图。"""

    position: int = Field(description="切块序号")
    content: str = Field(description="切块文本内容")
    pageNumber: int | None = Field(default=None, description="所在页码")
    tokenCount: int = Field(description="估算 token 数量")
