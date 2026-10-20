#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-20-ledger-app
#
# 覆盖范围：apps/ledger 独立构建产物（iframe 插件）是否可用、宿主 plugin-data 持久化、
# `tools` 权限与 dev agent 本地网关的真实 WS 回环、宿主前端类型检查与构建、安装脚本，
# 以及 README / 子应用 / 构建产物三方方法契约是否一致。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
PROBE_DIR="$(mktemp -d)"
trap 'rm -rf "$PROBE_DIR"' EXIT

# 执行一条验证命令并打印结果。
verify_step() {
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$*"
  echo '```'
  echo
  if "$@"; then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

# 在指定目录内执行命令（不用子 shell，保证 FAIL 能传出来）。
verify_step_in() {
  local dir="$1"; shift
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "cd ${dir} && $*"
  echo '```'
  echo
  if pushd "$dir" >/dev/null 2>&1; then
    if "$@"; then
      echo "结果：通过"
    else
      echo "结果：失败"
      FAIL=1
    fi
    popd >/dev/null 2>&1
  else
    echo "结果：失败（目录不存在：${dir}）"
    FAIL=1
  fi
  echo
}

echo "## 已执行的命令与结果"
echo

# 后端全量测试。已知 test_macos_open_treats_hanging_subprocess_as_handed_off 由仓库内他人未提交
# 改动引入（tests/test_host_api.py 缺少 subprocess 导入），与本 request 无关，这里显式 deselect
# 并在「未执行项」中列出，避免把别人的脏改动算成失败/通过。
verify_step_in "apps/desktop" \
  "后端全量测试（排除仓库既有失败的 test_host_api 用例）" \
  .venv/bin/python -m pytest -q \
  --deselect tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off

verify_step_in "apps/desktop" \
  "Ruff 检查本 request 相关 Python 文件" \
  .venv/bin/python -m ruff check desktop_app tests/test_plugin_data.py tests/test_dev_agent.py

verify_step_in "apps/ledger" "子应用构建（tsc --noEmit + vite build）" pnpm build

verify_step "子应用产物是合法 iframe 插件且带上 5 个方法名" bash -c '
  set -e
  dist=apps/ledger/dist
  test -f "$dist/index.html"
  test -f "$dist/manifest.json"
  test -f "$dist/icon.svg"
  ls "$dist"/assets/*.js >/dev/null
  node -e "
    const m = require(\"./apps/ledger/dist/manifest.json\");
    const assert = require(\"node:assert\");
    assert.strictEqual(m.id, \"ledger\");
    assert.strictEqual(m.type, \"iframe\");
    assert.strictEqual(m.entry, \"index.html\");
    for (const p of [\"storage\", \"tools\", \"notify\"]) assert.ok(m.permissions.includes(p), p);
  "
  for name in ledger_add_entry ledger_list_entries ledger_month_summary ledger_delete_entry ledger_list_categories; do
    grep -rq "$name" "$dist"/assets/*.js
  done
  echo "产物校验：通过"
'

verify_step_in "apps/desktop/front" "宿主前端类型检查" ./node_modules/.bin/tsc --noEmit

verify_step "宿主前端构建" pnpm --dir apps/desktop/front build

verify_step "安装脚本把 dist 同步到指定插件目录" bash -c "
  set -e
  target='${PROBE_DIR}/plugins'
  node apps/ledger/scripts/install-to-desktop.mjs --target \"\$target\" --json > '${PROBE_DIR}/install.json'
  cat '${PROBE_DIR}/install.json'
  test -f \"\$target/index.html\"
  test -f \"\$target/manifest.json\"
  ls \"\$target\"/assets/*.js >/dev/null
"

verify_step "README 与实现三方方法契约一致" bash -c '
  set -e
  for f in apps/ledger/src/lib/tools.ts apps/ledger/README.md apps/desktop/README.md; do
    for name in ledger_add_entry ledger_list_entries ledger_month_summary ledger_delete_entry ledger_list_categories; do
      grep -q "$name" "$f" || { echo "缺少 $name：$f"; exit 1; }
    done
  done
  echo "契约一致性：通过"
'

cat > "${PROBE_DIR}/probe_e2e.py" <<'PY'
"""端到端探针：真起宿主（TestClient），把已构建的 ledger dist 当作已安装插件，
验证静态托管、plugin-data 持久化、agent-config 与 dev agent 的真实 WS 工具回环。"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "apps/desktop"))

from desktop_app.manager import PluginManager  # noqa: E402
from desktop_app.plugin_data import PluginDataStore  # noqa: E402
from desktop_app.server import create_app  # noqa: E402


def main() -> int:
    tmp = Path(sys.argv[1])
    user_dir = tmp / "user-plugins"
    user_dir.mkdir(parents=True)
    shutil.copytree(ROOT / "apps/ledger/dist", user_dir / "ledger")

    manager = PluginManager(
        builtin_dir=ROOT / "apps/desktop/plugins",
        user_dir=user_dir,
        state_file=tmp / "state.json",
    )
    app = create_app(
        manager,
        plugin_data=PluginDataStore(tmp / "plugin-data"),
        dev_agent_enabled=True,
    )

    with TestClient(app) as client:
        items = client.get("/api/desktop/plugins").json()["items"]
        ledger = next(item for item in items if item["id"] == "ledger")
        assert ledger["enabled"] is True
        assert ledger["entryUrl"] == "/apps/ledger/index.html", ledger["entryUrl"]
        assert ledger["type"] == "iframe"

        page = client.get("/apps/ledger/index.html")
        assert page.status_code == 200, page.status_code
        assert 'id="root"' in page.text
        assets = re.findall(r'\./assets/[^"\']+', page.text)
        assert assets, "入口页面没有引用构建产物"
        for ref in assets:
            resp = client.get("/apps/ledger/" + ref[2:])
            assert resp.status_code == 200, (ref, resp.status_code)

        assert client.get("/api/desktop/plugin-data/ledger").json()["keys"] == []
        value = {"version": 1, "entries": [], "categories": {"expense": [], "income": []}}
        assert client.put("/api/desktop/plugin-data/ledger/ledger", json=value).json()["ok"] is True
        assert client.get("/api/desktop/plugin-data/ledger/ledger").json() == value
        assert client.get("/api/desktop/plugin-data/ledger").json()["keys"] == ["ledger"]

        config = client.get("/api/desktop/agent-config").json()
        assert config["enabled"] is True and config["mode"] == "dev", config
        assert config["endpoint"] == "/api/v1/ws/agents/local", config["endpoint"]

        with client.websocket_connect("/api/v1/ws/agents/local", subprotocols=["ai-agent.v1"]) as ws:
            ws.send_json(
                {
                    "id": "auth-1",
                    "type": "auth",
                    "protocolVersion": 1,
                    "timestamp": "2026-10-20T00:00:00Z",
                    "payload": {
                        "token": config["token"],
                        "platformId": config["platformId"],
                        "agentId": config["agentId"],
                        "protocolVersion": 1,
                        "sdkVersion": "0.2.0",
                    },
                }
            )
            ready = ws.receive_json()
            assert ready["type"] == "session_ready", ready["type"]

            ws.send_json(
                {
                    "id": "reg-1",
                    "type": "host_tools_register",
                    "protocolVersion": 1,
                    "sequence": 1,
                    "timestamp": "2026-10-20T00:00:01Z",
                    "payload": {
                        "tools": [
                            {
                                "name": "ledger_add_entry",
                                "description": "记一笔",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"amount": {"type": "number"}},
                                    "required": ["amount"],
                                },
                            }
                        ]
                    },
                }
            )
            ws.send_json(
                {
                    "id": "msg-1",
                    "type": "message_send",
                    "protocolVersion": 1,
                    "requestId": "req-1",
                    "sequence": 2,
                    "timestamp": "2026-10-20T00:00:02Z",
                    "payload": {"text": "今天午饭花了 35 块"},
                }
            )

            call = None
            for _ in range(40):
                event = ws.receive_json()
                if event["type"] == "host_tool_call":
                    call = event
                    break
            assert call is not None, "没有收到 host_tool_call"
            assert call["payload"]["name"] == "ledger_add_entry", call["payload"]["name"]
            assert call["payload"]["arguments"]["amount"] == 35.0, call["payload"]["arguments"]
            call_id = call["payload"]["callId"]

            ws.send_json(
                {
                    "id": "res-1",
                    "type": "host_tool_result",
                    "protocolVersion": 1,
                    "requestId": call_id,
                    "sequence": 3,
                    "timestamp": "2026-10-20T00:00:03Z",
                    "payload": {
                        "callId": call_id,
                        "result": {
                            "ok": True,
                            "entry": {"amount_yuan": 35.0, "category": "餐饮"},
                            "month_summary": {
                                "month": "2026-10",
                                "expense_yuan": 35.0,
                                "income_yuan": 0.0,
                                "balance_yuan": -35.0,
                            },
                        },
                    },
                }
            )

            completed = None
            for _ in range(60):
                event = ws.receive_json()
                if event["type"] == "message_completed":
                    completed = event
                    break
            assert completed is not None, "没有收到 message_completed"
            assert "35.00" in completed["payload"]["content"], completed["payload"]["content"]
            print("回复：", json.dumps(completed["payload"]["content"], ensure_ascii=False))

    print("端到端探针结论：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

verify_step "端到端探针（插件托管 + plugin-data + dev agent WS 工具回环）" \
  env PYTHONPATH=apps/desktop apps/desktop/.venv/bin/python "${PROBE_DIR}/probe_e2e.py" "${PROBE_DIR}/e2e"

# 真实进程验证：uvicorn 起宿主（DESKTOP_DEV_AGENT=1），用 websockets 客户端跑一次
# 「auth → host_tools_register → message_send → host_tool_call → host_tool_result → message_completed」，
# 证明 pyproject 新增的 websockets 依赖能让真实 WS 网关跑起来（不只是 TestClient 的内存传输）。
real_ws_probe() {
  local port=8799
  cat > "${PROBE_DIR}/probe_ws_real.py" <<'PYPROBE'
import asyncio
import json
import sys

import websockets


async def main() -> None:
    # 本机回环显式关闭代理探测：当前环境存在 SOCKS 代理变量，否则 websockets 会要求 python-socks。
    async with websockets.connect(sys.argv[1], subprotocols=["ai-agent.v1"], proxy=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "id": "auth-1",
                    "type": "auth",
                    "protocolVersion": 1,
                    "timestamp": "2026-10-20T00:00:00Z",
                    "payload": {
                        "token": "dev-local-token",
                        "platformId": "desktop",
                        "agentId": "local",
                        "protocolVersion": 1,
                        "sdkVersion": "0.2.0",
                    },
                }
            )
        )
        ready = json.loads(await ws.recv())
        assert ready["type"] == "session_ready", ready

        await ws.send(
            json.dumps(
                {
                    "id": "reg-1",
                    "type": "host_tools_register",
                    "protocolVersion": 1,
                    "sequence": 1,
                    "timestamp": "2026-10-20T00:00:01Z",
                    "payload": {
                        "tools": [
                            {
                                "name": "ledger_add_entry",
                                "description": "记一笔",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        ]
                    },
                }
            )
        )
        await ws.send(
            json.dumps(
                {
                    "id": "msg-1",
                    "type": "message_send",
                    "protocolVersion": 1,
                    "requestId": "req-1",
                    "sequence": 2,
                    "timestamp": "2026-10-20T00:00:02Z",
                    "payload": {"text": "今天午饭花了 35 块"},
                }
            )
        )

        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if event["type"] == "host_tool_call":
                call = event["payload"]
                assert call["name"] == "ledger_add_entry", call
                assert call["arguments"]["amount"] == 35.0, call
                await ws.send(
                    json.dumps(
                        {
                            "id": "res-1",
                            "type": "host_tool_result",
                            "protocolVersion": 1,
                            "requestId": call["callId"],
                            "sequence": 3,
                            "timestamp": "2026-10-20T00:00:03Z",
                            "payload": {
                                "callId": call["callId"],
                                "result": {
                                    "ok": True,
                                    "entry": {"amount_yuan": 35.0, "category": "餐饮"},
                                    "month_summary": {
                                        "month": "2026-10",
                                        "expense_yuan": 35.0,
                                        "income_yuan": 0.0,
                                        "balance_yuan": -35.0,
                                    },
                                },
                            },
                        }
                    )
                )
            elif event["type"] == "message_completed":
                content = event["payload"]["content"]
                assert "35.00" in content, content
                print("回复：", content.replace("\n", " / "))
                print("真实 WS 结论：通过")
                return


asyncio.run(main())
PYPROBE

  mkdir -p "${PROBE_DIR}/home"
  HOME="${PROBE_DIR}/home" PYTHONPATH=apps/desktop DESKTOP_DEV_AGENT=1 \
    apps/desktop/.venv/bin/python -m uvicorn desktop_app.server:create_app --factory \
    --host 127.0.0.1 --port "$port" >"${PROBE_DIR}/uvicorn.log" 2>&1 &
  local server_pid=$!
  local ok=1
  for _ in $(seq 1 50); do
    if curl -sf "http://127.0.0.1:${port}/api/health" >/dev/null; then ok=0; break; fi
    sleep 0.2
  done
  if [[ $ok -ne 0 ]]; then
    echo "宿主进程未在 10s 内就绪，uvicorn 日志："
    cat "${PROBE_DIR}/uvicorn.log"
    kill "$server_pid" 2>/dev/null
    return 1
  fi
  local client_status=0
  apps/desktop/.venv/bin/python "${PROBE_DIR}/probe_ws_real.py" "ws://127.0.0.1:${port}/api/v1/ws/agents/local" || client_status=$?
  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null
  return $client_status
}

verify_step "真实 uvicorn + websockets 客户端（DESKTOP_DEV_AGENT=1 的 WS 网关）" real_ws_probe

echo "## 未执行项与原因"
echo
echo "- 真机 GUI：在 pywebview 窗口里打开「记账」卡片、点击记一笔、看月汇总、重启应用后数据仍在——需要 macOS 图形会话与人工目视，脚本用 TestClient 验证了同一条服务链路（静态托管 + plugin-data + WS），但没有真正渲染界面。"
echo "- 浏览器里 ai-sdk 悬浮窗 ↔ 子应用方法注册这一跳：脚本用 TestClient 与真实 uvicorn + websockets 客户端模拟 ai-agent.v1 协议完成握手与工具回环，但没有启动 pywebview + 浏览器渲染 ai-sdk 悬浮窗，也没有验证 iframe 内 \`desktop.tools.register\` 经 tool-bridge 同步给助手的实际效果，需要打开宿主应用目视。"
echo "- \`tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off\`：仓库内他人未提交改动导致 \`NameError: name 'subprocess' is not defined\`（\`tests/test_host_api.py:210\`），与本 request 无关，已从 pytest 中 deselect，未修复该文件。"
echo "- \`apps/ledger\` 的浏览器层（localStorage 降级、向宿主迁移、界面交互）没有自动化测试：子应用本身不引入测试框架，相关行为在本轮实现时用临时断言脚本验证过，未固化为仓库内测试。"
echo "- Windows / Linux：本机只有 macOS 环境，未在其它平台执行。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 已由脚本证明：\`apps/ledger\` 能独立构建出合法 iframe 插件（manifest id/type/entry/permissions 正确，产物内含 5 个方法名）；宿主前端 \`tsc --noEmit\` 与生产构建通过；安装脚本能把 dist 同步到目标插件目录；宿主 plugin-data 接口能按插件隔离地写入/读取 JSON，且需要插件声明 \`storage\` 权限；\`GET /api/desktop/agent-config\` 在 \`dev_agent_enabled=True\` 时返回本地网关参数；真实 WS 会话能完成 \`session_ready\` → \`host_tools_register\` → \`message_send\` → \`host_tool_call(ledger_add_entry, amount=35)\` → \`host_tool_result\` → \`message_completed\`（含 35.00）的完整回环（TestClient 内存传输与真实 uvicorn + websockets 进程各验证一次）；5 个方法名在子应用实现、子应用 README、宿主 README 三处一致。"
echo "- 尚未证明：真实窗口里的界面交互与视觉、浏览器中 ai-sdk 悬浮窗到子应用工具注册的最后一跳（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已通过人工联调。"
echo "- 剩余风险：dev agent 是规则式 mock（关键词 + 金额正则），只用于本地闭环，不能代表真实模型对工具的选择；真实接入需 AI Base 后端签发 token 并把 \`ledger_*\` 绑定到 Agent 与 Embed Client、schema 指纹保持一致，这一步本 request 明确不在范围内。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
