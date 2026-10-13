"""插件 manifest 协议：模型定义与校验规则。"""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator
from pydantic import model_validator

logger = logging.getLogger(__name__)

# 插件 id 命名规则：小写字母/数字开头，仅允许字母、数字、下划线、连字符
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# 宿主 SDK 能力白名单；插件 manifest.permissions 声明所需能力，未声明则 SDK 对应方法不可用
KNOWN_PERMISSIONS = frozenset(
    {"notify", "settings", "storage", "events", "http", "platform", "log"}
)

# 子应用默认打开方式：inline=宿主壳内展开、browser=系统浏览器、window=新的原生窗口
OPEN_MODES = ("inline", "browser", "window")
DEFAULT_OPEN_MODE = "inline"


class PluginManifest(BaseModel):
    """插件元数据（对应插件目录中的 manifest.json）。"""

    id: str = Field(description="插件唯一标识，须与插件目录名一致")
    name: str = Field(description="插件展示名称")
    version: str = Field(description="插件版本号")
    description: str = Field(default="", description="插件描述")
    icon: str = Field(default="icon.svg", description="图标文件（包内相对路径）")
    entry: str = Field(default="index.html", description="入口页面（包内相对路径）")
    type: str = Field(
        default="iframe",
        description="子应用类型：iframe（三方 zip 应用）/ react（本项目原生应用）/ remote（从 URL 安装的远程壳插件）",
    )
    permissions: list[str] = Field(default_factory=list, description="声明所需的宿主能力")
    open_mode: str = Field(
        default=DEFAULT_OPEN_MODE,
        description="子应用默认打开方式：inline（宿主壳内展开）/ browser（系统浏览器）/ window（新的原生窗口）",
    )
    url: str | None = Field(
        default=None,
        description="远程插件目标地址（type=remote 时必填，仅允许 http/https）",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not PLUGIN_ID_PATTERN.match(value):
            raise ValueError(f"id 必须匹配 {PLUGIN_ID_PATTERN.pattern}")
        return value

    @field_validator("entry", "icon")
    @classmethod
    def _validate_relative_path(cls, value: str) -> str:
        """entry/icon 必须是包内相对路径，禁止绝对路径与 .. 穿越。"""
        if not value:
            raise ValueError("路径不能为空")
        pure = PurePosixPath(value.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("路径必须是包内相对路径，禁止绝对路径与 .. 穿越")
        return value

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in {"iframe", "react", "remote"}:
            raise ValueError("type 仅支持 iframe、react 或 remote")
        return value

    @field_validator("open_mode", mode="before")
    @classmethod
    def _normalize_open_mode(cls, value: object) -> str:
        """非法值宽容回退 inline。

        open_mode 只是「卡片点击后怎么打开」的展示策略、不是安全边界，
        一个笔误不该让整个插件装不上；处理方式与 permissions 的宽容策略一致。
        """
        normalized = value.strip().lower() if isinstance(value, str) else ""
        if normalized in OPEN_MODES:
            return normalized
        if normalized:
            logger.warning("manifest.open_mode=%r 不是合法打开方式，回退 %s", value, DEFAULT_OPEN_MODE)
        return DEFAULT_OPEN_MODE

    @model_validator(mode="after")
    def _validate_remote(self) -> "PluginManifest":
        """remote 类型必须声明公网 http/https 的 url；本地类型不允许携带 url。"""
        if self.type == "remote":
            if not self.url:
                raise ValueError("type=remote 时必须提供 url 字段")
            if not self.url.lower().startswith(("http://", "https://")):
                raise ValueError("remote 插件的 url 仅支持 http/https")
        elif self.url is not None:
            raise ValueError("仅 type=remote 插件允许声明 url 字段")
        return self

    def unknown_permissions(self) -> list[str]:
        """返回不在宿主白名单中的能力名（安装时警告但允许，保证向后兼容）。"""
        return sorted(set(self.permissions) - KNOWN_PERMISSIONS)
