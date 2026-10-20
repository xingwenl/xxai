#!/usr/bin/env python3
"""把桌面记账子应用的方法注册进 AI Base（一次性 / 可重复执行的运维脚本）。

为什么需要它：宿主工具（host tool）能不能被模型调用，由三层配置共同裁决——

1. 平台侧 ``HostToolPolicy``（名称、描述、inputSchema、sideEffect、确认策略）；
2. ``AgentHostTool``（该 Agent 是否启用）与 ``EmbedClientHostTool``（该 Client 是否放行）；
3. 页面注册时的 ``inputSchema`` 必须与策略的 ``schema_fingerprint`` 完全一致
   （后端按 ``sort_keys`` + 紧凑分隔符的 JSON 求 sha256）。

三层缺一层，工具调用都会被静默忽略。本脚本读 ``apps/ledger/tools.json``
（页面注册的唯一契约来源）落库并完成绑定，同时把桌面页面来源加进 Client 的
``allowed_origins``（token 的 origin 与 WebSocket 握手 Origin 严格比对）。

用法::

    python apps/desktop/scripts/configure_ai_base.py
    python apps/desktop/scripts/configure_ai_base.py --dry-run
    python apps/desktop/scripts/configure_ai_base.py --origin http://127.0.0.1:8443

脚本只用标准库，可以脱离桌面应用单独运行；出错时打印后端返回的中文原因并以 1 退出。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TOOLS_FILE = REPO_ROOT / "apps" / "ledger" / "tools.json"
DEFAULT_DESKTOP_CONFIG = Path.home() / ".desktop-app" / "agent.json"
DEFAULT_ORIGINS = ("http://127.0.0.1:8765", "http://127.0.0.1:8443")
REQUEST_TIMEOUT = 15.0


class ApiError(RuntimeError):
    """后端返回的可读错误。"""


def canonical_fingerprint(value: Any) -> str:
    """与后端 ``host_tool.services.canonical_fingerprint`` 保持同一算法。"""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None

    def set_token(self, token: str) -> None:
        self._token = token

    def request(self, method: str, path: str, body: Any | None = None) -> Any:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return None
                payload = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise ApiError(f"{method} {path} → HTTP {exc.code}：{_error_detail(exc)}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"无法连接 {url}：{exc.reason}") from exc
        if isinstance(payload, dict) and "success" in payload and not payload["success"]:
            raise ApiError(f"{method} {path} 失败：{payload.get('message') or payload}")
        return payload.get("data") if isinstance(payload, dict) else payload


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except OSError:
        return "未知错误"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:300]
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or raw
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                location = ".".join(str(part) for part in first.get("loc", []))
                return f"{location}: {first.get('msg')}"
        return str(detail)[:300]
    return raw[:300]


def load_desktop_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(f"读取桌面配置失败 {path}：{exc}") from exc
    return payload if isinstance(payload, dict) else {}


def load_tool_contract(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(f"读取工具契约失败 {path}：{exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise ApiError(f"工具契约必须是数组：{path}")
    return payload


def ensure_origins(
    api: ApiClient,
    platform_id: int,
    client: dict[str, Any],
    origins: list[str],
    *,
    dry_run: bool,
) -> list[str]:
    """把桌面来源并入 Client 的 allowed_origins（后端要求精确 origin）。"""
    existing = [str(item) for item in client.get("allowed_origins") or []]
    normalized = sorted({item.rstrip("/") for item in [*existing, *origins]})
    if normalized == sorted({item.rstrip("/") for item in existing}):
        return existing
    if dry_run:
        return normalized
    api.request(
        "PATCH",
        f"/api/v1/platforms/{platform_id}/embed-clients/{client['client_id']}",
        {"allowed_origins": normalized},
    )
    return normalized


def upsert_policy(
    api: ApiClient,
    platform_id: int,
    tool: dict[str, Any],
    existing: dict[str, Any] | None,
    *,
    confirmation_policy: str,
    dry_run: bool,
) -> tuple[int, str]:
    """创建或更新策略，返回 (tool_id, 动作说明)。"""
    name = str(tool["name"])
    desired = {
        "description": str(tool.get("description") or name),
        "input_schema": tool.get("inputSchema") or {"type": "object"},
        "side_effect": str(tool.get("sideEffect") or "none"),
        "confirmation_policy": confirmation_policy,
    }
    if existing is None:
        if dry_run:
            return 0, f"将创建策略 {name}"
        created = api.request(
            "POST",
            f"/api/v1/platforms/{platform_id}/host-tools",
            {"name": name, **desired},
        )
        tool_id = int(created["id"])
        # 创建接口不接收 is_enabled（模型默认 false），必须再 PATCH 一次才会被网关采纳。
        api.request(
            "PATCH",
            f"/api/v1/platforms/{platform_id}/host-tools/{tool_id}",
            {"is_enabled": True},
        )
        return tool_id, f"已创建策略 {name} (id={tool_id})"

    tool_id = int(existing["id"])
    fingerprint_matches = existing.get("schema_fingerprint") == canonical_fingerprint(
        desired["input_schema"]
    )
    needs_update = (
        not fingerprint_matches
        or existing.get("description") != desired["description"]
        or existing.get("side_effect") != desired["side_effect"]
        or existing.get("confirmation_policy") != desired["confirmation_policy"]
    )
    if not needs_update:
        return tool_id, f"策略已是最新 {name} (id={tool_id})"
    if dry_run:
        return tool_id, f"将更新策略 {name} (id={tool_id})"
    # 注意：后端在 input_schema 变化时会把 is_enabled 置 False，因此更新后必须显式重新启用。
    api.request(
        "PATCH",
        f"/api/v1/platforms/{platform_id}/host-tools/{tool_id}",
        desired,
    )
    api.request(
        "PATCH",
        f"/api/v1/platforms/{platform_id}/host-tools/{tool_id}",
        {"is_enabled": True},
    )
    return tool_id, f"已更新策略 {name} (id={tool_id})"


def bind(
    api: ApiClient,
    platform_id: int,
    agent_id: int,
    client_id: str,
    tool_id: int,
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    api.request(
        "PUT", f"/api/v1/platforms/{platform_id}/agents/{agent_id}/host-tools/{tool_id}"
    )
    api.request(
        "PUT",
        f"/api/v1/platforms/{platform_id}/embed-clients/{client_id}/host-tools/{tool_id}",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    desktop_config = load_desktop_config(DEFAULT_DESKTOP_CONFIG)
    parser = argparse.ArgumentParser(
        description="把 apps/ledger 的方法注册进 AI Base（策略 + Agent/Client 绑定 + 来源）",
    )
    parser.add_argument(
        "--api-base",
        default=desktop_config.get("baseUrl")
        or os.environ.get("AI_BASE_URL")
        or "http://127.0.0.1:8000",
        help="AI Base 服务地址（默认读桌面配置 / AI_BASE_URL / http://127.0.0.1:8000）",
    )
    parser.add_argument(
        "--account",
        default=os.environ.get("AI_BASE_ACCOUNT", "admin"),
        help="管理员账号（种子环境默认 admin）",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("AI_BASE_PASSWORD", "admin123456"),
        help="管理员密码（种子环境默认 admin123456）",
    )
    parser.add_argument("--platform-id", type=int, default=1, help="平台 ID（种子环境为 1）")
    parser.add_argument(
        "--agent-id",
        type=int,
        default=int(desktop_config.get("agentId") or os.environ.get("EMBED_AGENT_ID") or 1),
        help="Agent ID（默认读桌面配置 / EMBED_AGENT_ID / 1）",
    )
    parser.add_argument(
        "--client-id",
        default=desktop_config.get("clientId") or os.environ.get("EMBED_CLIENT_ID"),
        help="Embed Client 的公开 client_id（默认读桌面配置 / EMBED_CLIENT_ID）",
    )
    parser.add_argument(
        "--tools",
        default=str(DEFAULT_TOOLS_FILE),
        help="工具契约文件（默认 apps/ledger/tools.json）",
    )
    parser.add_argument(
        "--origin",
        action="append",
        default=[],
        help="额外允许的页面来源，可重复；默认同时允许 127.0.0.1:8765 与 :8443",
    )
    parser.add_argument(
        "--confirm-financial",
        action="store_true",
        help="有副作用的工具要求每次确认（默认 auto，便于无人值守演示）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要做的变更")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.client_id:
        print(
            "缺少 Embed Client ID：先在桌面「设置 → 智能体后端」填写并保存，"
            "或用 --client-id / EMBED_CLIENT_ID 指定。",
            file=sys.stderr,
        )
        return 1
    api = ApiClient(str(args.api_base))
    try:
        token = api.request(
            "POST",
            "/api/v1/auth/login",
            {"account": args.account, "password": args.password},
        )
        api.set_token(str(token["access_token"]))
        clients = api.request(
            "GET", f"/api/v1/platforms/{args.platform_id}/embed-clients"
        ) or []
        client = next(
            (item for item in clients if item.get("client_id") == args.client_id), None
        )
        if client is None:
            raise ApiError(
                f"平台 {args.platform_id} 下找不到 Embed Client {args.client_id}；"
                "请先执行 apps/backend/scripts/seed_dev_env.py 或在后台创建。"
            )
        origins = ensure_origins(
            api,
            args.platform_id,
            client,
            [*DEFAULT_ORIGINS, *args.origin],
            dry_run=args.dry_run,
        )
        print(f"Client {args.client_id} 允许来源：{', '.join(origins)}")

        tools = load_tool_contract(Path(args.tools))
        policies = api.request("GET", f"/api/v1/platforms/{args.platform_id}/host-tools") or []
        by_name = {item["name"]: item for item in policies}
        for tool in tools:
            confirmation = (
                "always"
                if args.confirm_financial and tool.get("sideEffect") not in (None, "none")
                else "auto"
            )
            tool_id, action = upsert_policy(
                api,
                args.platform_id,
                tool,
                by_name.get(str(tool["name"])),
                confirmation_policy=confirmation,
                dry_run=args.dry_run,
            )
            print(f"- {action}")
            if tool_id:
                bind(
                    api,
                    args.platform_id,
                    args.agent_id,
                    args.client_id,
                    tool_id,
                    dry_run=args.dry_run,
                )
        if args.dry_run:
            print("dry-run：未写入任何变更")
        else:
            print(
                f"完成：{len(tools)} 个方法已绑定 Agent {args.agent_id} 与 Client {args.client_id}。"
            )
            print("提示：确认桌面页面来源已加入后端 CORS_ORIGINS（WebSocket 不受 CORS 约束，但 REST 换 token 同源即可）。")
        return 0
    except ApiError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
