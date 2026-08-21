"""插件 manifest 协议：模型定义与校验规则。"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator

# 插件 id 命名规则：小写字母/数字开头，仅允许字母、数字、下划线、连字符
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# 宿主 SDK 能力白名单；插件 manifest.permissions 声明所需能力，未声明则 SDK 对应方法不可用
KNOWN_PERMISSIONS = frozenset(
    {"notify", "settings", "storage", "events", "http", "platform", "log"}
)


class PluginManifest(BaseModel):
    """插件元数据（对应插件目录中的 manifest.json）。"""

    id: str = Field(description="插件唯一标识，须与插件目录名一致")
    name: str = Field(description="插件展示名称")
    version: str = Field(description="插件版本号")
    description: str = Field(default="", description="插件描述")
    icon: str = Field(default="icon.svg", description="图标文件（包内相对路径）")
    entry: str = Field(default="index.html", description="入口页面（包内相对路径）")
    permissions: list[str] = Field(default_factory=list, description="声明所需的宿主能力")

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

    def unknown_permissions(self) -> list[str]:
        """返回不在宿主白名单中的能力名（安装时警告但允许，保证向后兼容）。"""
        return sorted(set(self.permissions) - KNOWN_PERMISSIONS)
