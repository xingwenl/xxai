"""桌面宿主的智能体后端配置，以及向 AI Base 换取短期 Embed token。

为什么放在宿主进程而不是渲染层：``client_secret`` 等同于签发权限，一旦下发到页面
就等于把任意 Agent/工具的签发权交给了页面；因此渲染层只拿到短期 token，配置与换发
都留在内嵌 FastAPI 里。配置文件位于 ``~/.desktop-app/agent.json``，权限 0600。

本模块只依赖标准库，避免给桌面端引入新的运行时依赖。
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import paths

# 配置文件名（位于 user_data_dir 下）
CONFIG_FILENAME = "agent.json"

# 换 token 的请求超时（秒）：桌面端宁可失败快，也不要卡住悬浮窗挂载
TOKEN_TIMEOUT_SECONDS = 10.0

# 只允许本机页面来源：token 的 origin 会和 WebSocket 握手 Origin 严格比对，
# 允许任意来源既没有意义（后端 allowed_origins 会拒绝），也会掩盖配置错误。
LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})

# 记账子应用默认暴露的方法；配置里可覆盖，但缺省值应与 apps/ledger/tools.json 一致
DEFAULT_HOST_TOOL_NAMES: tuple[str, ...] = (
    "ledger_add_entry",
    "ledger_list_entries",
    "ledger_month_summary",
    "ledger_delete_entry",
    "ledger_list_categories",
)


class AgentConfigError(Exception):
    """智能体后端配置或 token 换取过程中的可读错误。"""


class AgentConfigNotConfigured(AgentConfigError):
    """尚未配置智能体后端（与「配置有误」区分，前端据此提示去设置页）。"""


def _require_non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentConfigError(f"{label}不能为空")
    return value.strip()


def _require_agent_id(value: Any) -> int:
    try:
        agent_id = int(value)
    except (TypeError, ValueError) as exc:
        raise AgentConfigError("Agent ID 必须是正整数") from exc
    if agent_id < 1:
        raise AgentConfigError("Agent ID 必须是正整数")
    return agent_id


def _require_base_url(value: Any) -> str:
    base_url = _require_non_empty(value, "AI Base 地址").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentConfigError("AI Base 地址必须是 http(s) 地址，例如 http://127.0.0.1:8000")
    return base_url


@dataclass(frozen=True)
class AgentBackendConfig:
    """指向某个 AI Base Embed Client 的连接参数。

    字段含义与 ``POST /api/v1/embed/tokens`` 的入参一一对应；``host_tool_names``
    只是「本轮希望启用的方法名」，后端仍会与 Client 绑定、Agent 绑定、
    页面注册三方求交集，因此这里写多做不了越权。
    """

    base_url: str
    client_id: str
    client_secret: str
    agent_id: int
    host_tool_names: tuple[str, ...] = field(default=DEFAULT_HOST_TOOL_NAMES)
    display_name: str = "桌面用户"
    external_user_id: str = "desktop-local"

    def __post_init__(self) -> None:
        # 归一化并校验，保证从文件反序列化出来的对象也满足约束
        object.__setattr__(self, "base_url", _require_base_url(self.base_url))
        object.__setattr__(
            self, "client_id", _require_non_empty(self.client_id, "Embed Client ID")
        )
        object.__setattr__(
            self,
            "client_secret",
            _require_non_empty(self.client_secret, "Embed Client Secret"),
        )
        object.__setattr__(self, "agent_id", _require_agent_id(self.agent_id))
        names = tuple(
            str(name).strip()
            for name in self.host_tool_names
            if isinstance(name, str) and name.strip()
        )
        object.__setattr__(self, "host_tool_names", names)

    @property
    def token_url(self) -> str:
        return f"{self.base_url}/api/v1/embed/tokens"

    @property
    def ws_endpoint(self) -> str:
        """WebSocket 端点：http→ws、https→wss，路径固定为 Agent 网关。"""
        scheme = "wss" if self.base_url.startswith("https://") else "ws"
        host = self.base_url.split("://", 1)[1]
        return f"{scheme}://{host}/api/v1/ws/agents/{self.agent_id}"

    @property
    def ws_origin(self) -> str:
        """桌面页面被打开时使用的来源；后端会把它与 WebSocket 握手 Origin 比对。"""
        return self.base_url

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseUrl": self.base_url,
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "agentId": self.agent_id,
            "hostToolNames": list(self.host_tool_names),
            "displayName": self.display_name,
            "externalUserId": self.external_user_id,
        }

    def redacted(self) -> dict[str, Any]:
        """给渲染层看的配置：不含 secret，只标注是否已保存。"""
        return {
            "baseUrl": self.base_url,
            "clientId": self.client_id,
            "agentId": self.agent_id,
            "hostToolNames": list(self.host_tool_names),
            "displayName": self.display_name,
            "externalUserId": self.external_user_id,
            "hasSecret": True,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentBackendConfig:
        host_tools = payload.get("hostToolNames")
        if host_tools is None:
            host_tools = DEFAULT_HOST_TOOL_NAMES
        if not isinstance(host_tools, (list, tuple)):
            raise AgentConfigError("hostToolNames 必须是字符串数组")
        return cls(
            base_url=payload.get("baseUrl", ""),
            client_id=payload.get("clientId", ""),
            client_secret=payload.get("clientSecret", ""),
            agent_id=payload.get("agentId", 0),
            host_tool_names=tuple(host_tools),
            display_name=str(payload.get("displayName") or "桌面用户"),
            external_user_id=str(payload.get("externalUserId") or "desktop-local"),
        )


class AgentConfigStore:
    """``~/.desktop-app/agent.json`` 的读写；文件不存在表示未配置。"""

    def __init__(self, config_file: Path | None = None) -> None:
        self._config_file = config_file

    @property
    def path(self) -> Path:
        return self._config_file or (paths.user_data_dir() / CONFIG_FILENAME)

    def load(self) -> AgentBackendConfig | None:
        path = self.path
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentConfigError(f"读取智能体配置失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise AgentConfigError("智能体配置格式错误：根节点必须是对象")
        # 缺 secret 的配置视为无效，交给用户重新填写，避免半配置状态换 token 必然失败
        if not payload.get("clientSecret"):
            raise AgentConfigError("智能体配置缺少 Embed Client Secret，请在设置页重新填写")
        return AgentBackendConfig.from_dict(payload)

    def save(self, config: AgentBackendConfig) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".agent-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def clear(self) -> bool:
        path = self.path
        if not path.is_file():
            return False
        path.unlink()
        return True


def validate_local_origin(origin: str) -> str:
    """校验渲染层上报的页面来源，只接受本机 http(s) 来源。"""
    value = (origin or "").strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in LOCAL_HOSTNAMES
        or parsed.port is None
    ):
        raise AgentConfigError(f"仅支持本机页面来源，收到：{origin!r}")
    return value


def _platform_id_from_token(token: str) -> int | None:
    """从 Embed token 的 payload 里读出 platform_id（不验签，仅用于前端回填）。"""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    segment = parts[1]
    padding = "=" * (-len(segment) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(segment + padding))
    except (ValueError, json.JSONDecodeError):
        return None
    platform_id = payload.get("platform_id")
    return int(platform_id) if isinstance(platform_id, int) else None


def issue_agent_token(
    store: AgentConfigStore,
    origin: str,
    *,
    timeout: float = TOKEN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """用服务端保存的 Client 凭证换一张短期 token，并给出前端连接所需参数。"""
    config = store.load()
    if config is None:
        raise AgentConfigNotConfigured("尚未配置 AI Base 智能体后端")
    valid_origin = validate_local_origin(origin)
    body = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "agent_id": config.agent_id,
        "external_user_id": config.external_user_id,
        "display_name": config.display_name,
        "origin": valid_origin,
        "host_tool_names": list(config.host_tool_names),
    }
    request = urllib.request.Request(
        config.token_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _read_error_detail(exc)
        raise AgentConfigError(
            f"AI Base 拒绝签发 token（HTTP {exc.code}）：{detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise AgentConfigError(
            f"无法连接 AI Base 后端 {config.base_url}：{exc.reason}"
        ) from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise AgentConfigError(f"AI Base 响应异常：{exc}") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("access_token"):
        raise AgentConfigError("AI Base 响应缺少 access_token")
    token = str(data["access_token"])
    platform_id = _platform_id_from_token(token)
    return {
        "token": token,
        "expiresIn": int(data.get("expires_in") or 0),
        "endpoint": config.ws_endpoint,
        "platformId": platform_id,
        "agentId": config.agent_id,
        "displayName": config.display_name,
        "mode": "remote",
    }


def _read_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except OSError:
        return "未知错误"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:300] or "未知错误"
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or raw
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                return str(first.get("msg") or first)
        return str(detail)[:300]
    return raw[:300] or "未知错误"
