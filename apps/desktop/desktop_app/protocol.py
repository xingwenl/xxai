"""插件 manifest 协议：模型定义与校验规则。"""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic import model_validator

logger = logging.getLogger(__name__)

# 插件 id 命名规则：小写字母/数字开头，仅允许字母、数字、下划线、连字符
PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# 宿主 SDK 能力白名单；插件 manifest.permissions 声明所需能力，未声明则 SDK 对应方法不可用
KNOWN_PERMISSIONS = frozenset(
    # tools：允许子应用向全局助手注册可调用的方法（宿主工具桥）
    {"notify", "settings", "storage", "events", "http", "platform", "log", "tools"}
)

# 子应用默认打开方式：inline=宿主壳内展开、browser=系统浏览器、window=新的原生窗口
OPEN_MODES = ("inline", "browser", "window")
DEFAULT_OPEN_MODE = "inline"

# 配置项类型白名单：宿主按类型渲染控件（文本框/数字/开关/下拉）并做取值校验
SETTING_TYPES = ("text", "number", "boolean", "select")

# 单个插件最多声明的配置项与下拉候选项数量，避免 manifest 变成巨型表单
MAX_SETTINGS = 32
MAX_SETTING_OPTIONS = 50

# 配置键：小写字母开头，仅允许字母、数字、下划线、连字符，最长 64 字符
SETTING_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class SettingOption(BaseModel):
    """select 类型的候选项：label 展示给用户，value 是落盘的字符串取值。"""

    label: str = Field(description="下拉展示文案")
    value: str = Field(description="保存的取值")

    @field_validator("label", "value")
    @classmethod
    def _validate_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("候选项的 label/value 不能为空")
        return value


class PluginSetting(BaseModel):
    """子应用声明的一项宿主配置。

    宿主按 ``type`` 渲染控件并在保存时校验取值，值落 ``~/.desktop-app/plugin-config/<id>.json``；
    子应用通过 SDK 的 ``settings.getConfig()`` 只读。声明式配置的好处是宿主与子应用都不必
    重复实现表单和校验，schema 即 UI。
    """

    key: str = Field(description="配置键，也是落盘 JSON 的字段名")
    label: str = Field(description="表单展示文案")
    type: str = Field(default="text", description="控件类型：text / number / boolean / select")
    default: Any = Field(default=None, description="默认值，类型须与 type 匹配")
    description: str = Field(default="", description="表单下方的说明文案")
    options: list[SettingOption] = Field(default_factory=list, description="select 的候选项")
    min: float | None = Field(default=None, description="number 的最小值（含）")
    max: float | None = Field(default=None, description="number 的最大值（含）")

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not SETTING_KEY_PATTERN.match(value):
            raise ValueError(f"配置键必须匹配 {SETTING_KEY_PATTERN.pattern}")
        return value

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("配置项的 label 不能为空")
        return value

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in SETTING_TYPES:
            raise ValueError(f"配置项 type 仅支持 {'、'.join(SETTING_TYPES)}")
        return value

    @field_validator("options")
    @classmethod
    def _validate_options(cls, value: list[SettingOption]) -> list[SettingOption]:
        if len(value) > MAX_SETTING_OPTIONS:
            raise ValueError(f"select 候选项最多 {MAX_SETTING_OPTIONS} 个")
        values = [item.value for item in value]
        if len(set(values)) != len(values):
            raise ValueError("select 候选项的 value 不能重复")
        return value

    @model_validator(mode="after")
    def _validate_consistency(self) -> "PluginSetting":
        """默认值必须与类型一致；select 的默认值必须是候选项之一；min/max 只属于 number。"""
        if self.type == "select":
            if not self.options:
                raise ValueError("type=select 时必须提供非空 options")
            allowed = {item.value for item in self.options}
            if not isinstance(self.default, str) or self.default not in allowed:
                raise ValueError(
                    f"select 的 default 必须是候选项 value 之一（当前 {self.default!r}）"
                )
        elif self.type == "boolean":
            if not isinstance(self.default, bool):
                raise ValueError("boolean 配置项的 default 必须是 true/false")
        elif self.type == "number":
            # bool 是 int 的子类，这里要显式排除，否则 default: true 会被当成数字
            if isinstance(self.default, bool) or not isinstance(self.default, (int, float)):
                raise ValueError("number 配置项的 default 必须是数字")
            if self.min is not None and self.max is not None and self.min > self.max:
                raise ValueError(f"number 配置项的 min（{self.min}）不能大于 max（{self.max}）")
        else:
            if not isinstance(self.default, str):
                raise ValueError("text 配置项的 default 必须是字符串")
        if self.type != "number" and (self.min is not None or self.max is not None):
            raise ValueError("min/max 仅对 number 配置项生效")
        return self


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
    settings: list[PluginSetting] = Field(
        default_factory=list,
        description="子应用声明的宿主配置项；设置页据此渲染表单，值存宿主 plugin-config 目录",
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

    @field_validator("settings")
    @classmethod
    def _validate_settings(cls, value: list[PluginSetting]) -> list[PluginSetting]:
        """配置项数量与键唯一性校验；键重复会让设置页表单互相覆盖。"""
        if len(value) > MAX_SETTINGS:
            raise ValueError(f"settings 最多声明 {MAX_SETTINGS} 项（当前 {len(value)}）")
        keys = [item.key for item in value]
        duplicated = sorted({key for key in keys if keys.count(key) > 1})
        if duplicated:
            raise ValueError(f"settings 的 key 不能重复：{'、'.join(duplicated)}")
        return value

    @model_validator(mode="after")
    def _validate_remote(self) -> "PluginManifest":
        """remote 类型必须声明公网 http/https 的 url；本地类型不允许携带 url。"""
        if self.type == "remote":
            if not self.url:
                raise ValueError("type=remote 时必须提供 url 字段")
            if not self.url.lower().startswith(("http://", "https://")):
                raise ValueError("remote 插件的 url 仅支持 http/https")
            # 远程壳页面不注入 SDK，声明配置项也无法读取，直接在 manifest 层拒绝
            if self.settings:
                raise ValueError("type=remote 的插件不支持 settings[]（远程壳不注入 SDK）")
        elif self.url is not None:
            raise ValueError("仅 type=remote 插件允许声明 url 字段")
        return self

    def unknown_permissions(self) -> list[str]:
        """返回不在宿主白名单中的能力名（安装时警告但允许，保证向后兼容）。"""
        return sorted(set(self.permissions) - KNOWN_PERMISSIONS)
