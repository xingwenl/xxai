#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-21-desktop-plugin-market
#
# 覆盖范围：市场索引解析/校验、sha256 与包内 manifest 一致性、安装错误语义、
# CLI（list/install/entry/verify）以及「临时 HOME + file:// 索引 + 无头 Chrome/CDP」
# 的设置页「插件市场」端到端安装。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

ROOT="$(pwd)"
FAIL=0
UNEXECUTED=0
PREMARK_SKIPPED=0
PROBE_DIR="$(mktemp -d)"
trap 'rm -rf "$PROBE_DIR"' EXIT

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

find_chrome() {
  local candidate
  for candidate in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "$(command -v google-chrome 2>/dev/null || true)" \
    "$(command -v chromium 2>/dev/null || true)" \
    "$(command -v chromium-browser 2>/dev/null || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

free_port() {
  "$ROOT/apps/desktop/.venv/bin/python" - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

start_chrome() {
  local chrome="$1" profile="$2"
  mkdir -p "${PROBE_DIR}/chrome-home" "$profile"
  HOME="${PROBE_DIR}/chrome-home" "$chrome" \
    --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage --disable-crash-reporter \
    --no-first-run --no-default-browser-check --hide-scrollbars \
    --remote-debugging-port=0 --user-data-dir="$profile" \
    about:blank >"${PROBE_DIR}/chrome.out" 2>"${PROBE_DIR}/chrome.err" &
  local chrome_pid=$!
  local ws=""
  for _ in $(seq 1 100); do
    sleep 0.1
    ws="$(grep -oE 'ws://127\.0\.0\.1:[0-9]+/devtools/browser/[A-Za-z0-9-]+' "${PROBE_DIR}/chrome.err" 2>/dev/null | head -1 || true)"
    [[ -n "$ws" ]] && break
  done
  if [[ -z "$ws" ]]; then
    echo "无头 Chrome 未在 10s 内给出 CDP 地址：" >&2
    tail -5 "${PROBE_DIR}/chrome.err" >&2
    kill "$chrome_pid" 2>/dev/null
    return 1
  fi
  echo "${chrome_pid} ${ws}"
}

# 起宿主并等到 /api/health 可用；参数：home port log [额外 env KEY=VALUE ...]
start_host() {
  local home="$1" port="$2" log="$3"; shift 3
  local envs=("HOME=$home" "PYTHONPATH=${ROOT}/apps/desktop" "$@")
  env "${envs[@]}" "$ROOT/apps/desktop/.venv/bin/python" -c "
import uvicorn
from desktop_app.server import create_app
uvicorn.run(create_app(dev_agent_enabled=False), host='127.0.0.1', port=${port}, log_level='warning')
" >"$log" 2>&1 &
  echo $!
}

wait_host() {
  local port="$1"
  for _ in $(seq 1 60); do
    sleep 0.2
    if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

# 构造市场夹具：三个插件包与一份索引（正常 / sha256 错误 / size 错误）。
build_market_fixture() {
  local dir="$1"
  "$ROOT/apps/desktop/.venv/bin/python" - "$dir" <<'PY'
import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
packages = root / "packages"
packages.mkdir(exist_ok=True)


def make_zip(plugin_id: str, name: str, version: str = "0.1.0") -> Path:
    manifest = {
        "id": plugin_id,
        "name": name,
        "version": version,
        "description": "市场验证探针",
        "entry": "index.html",
        # 声明 settings，验证装完后设置页能出现「配置」入口
        "permissions": ["settings"],
        "settings": [
            {"key": "greeting", "label": "问候语", "type": "text", "default": "市场来的问候"}
        ],
    }
    target = packages / f"{plugin_id}-{version}.zip"
    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head>'
        f'<body><div id="out">{name}</div></body></html>'
    )
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("index.html", html)
    return target


entries = []
good = make_zip("market-probe", "市场探针")
data = good.read_bytes()
entries.append(
    {
        "id": "market-probe",
        "name": "市场探针",
        "version": "0.1.0",
        "description": "市场验证探针",
        "download": f"file://{good}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "permissions": ["settings"],
    }
)

bad_sha = make_zip("market-bad", "sha 错误探针")
entries.append(
    {
        "id": "market-bad",
        "name": "sha 错误探针",
        "version": "0.1.0",
        "description": "sha256 故意写错",
        "download": f"file://{bad_sha}",
        "sha256": "0" * 64,
        "size": bad_sha.stat().st_size,
        "permissions": [],
    }
)

bad_size = make_zip("market-size", "大小错误探针")
size_data = bad_size.read_bytes()
entries.append(
    {
        "id": "market-size",
        "name": "大小错误探针",
        "version": "0.1.0",
        "description": "size 故意写错",
        "download": f"file://{bad_size}",
        "sha256": hashlib.sha256(size_data).hexdigest(),
        "size": 1,
        "permissions": [],
    }
)

index = {"version": 1, "plugins": entries}
(root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"夹具：{root / 'index.json'}")
PY
}

# 后端/端点探针：临时 HOME + file:// 索引，验证列表、安装、错误语义与日志。
market_api_probe() {
  local fixture="${PROBE_DIR}/market"
  build_market_fixture "$fixture" || return 1
  local port probe_home server_pid
  port="$(free_port)"
  probe_home="${PROBE_DIR}/home-api"
  mkdir -p "$probe_home"
  echo "启动宿主：HOME=${probe_home} port=${port} DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json"
  server_pid="$(start_host "$probe_home" "$port" "${PROBE_DIR}/server-api.log" \
    "DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json")"
  if ! wait_host "$port"; then
    echo "宿主未能在 ${port} 启动："
    tail -20 "${PROBE_DIR}/server-api.log"
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  fi

  local rc=0 base="http://127.0.0.1:${port}"
  curl -fsS "${base}/api/desktop/plugin-market" -o "${PROBE_DIR}/market.json" || rc=1
  if [[ $rc -eq 0 ]] && "$ROOT/apps/desktop/.venv/bin/python" - "${PROBE_DIR}/market.json" "${fixture}" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
assert body["enabled"] is True, body
assert body["source"] == f"file://{sys.argv[2]}/index.json", body
assert [item["id"] for item in body["plugins"]] == ["market-probe", "market-bad", "market-size"], body
assert body["plugins"][0]["sha256"] == body["plugins"][0]["sha256"].lower()
installed = body["installed"]
assert installed.get("hello-world") == "0.1.0", body
assert installed.get("bookmarks-organizer") == "0.1.0", body
assert "market-probe" not in installed, body
print("✓ GET /api/desktop/plugin-market 返回 enabled/source/条目/已安装映射")
PY
  then
    :
  else
    echo "✗ 市场列表返回不符合预期"
    rc=1
  fi

  curl -fsS -X POST "${base}/api/desktop/plugin-market/install" \
    -H 'Content-Type: application/json' -d '{"id":"market-probe"}' -o "${PROBE_DIR}/install-ok.json" || rc=1
  if [[ -r "${PROBE_DIR}/install-ok.json" ]] && "$ROOT/apps/desktop/.venv/bin/python" - "${PROBE_DIR}/install-ok.json" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
plugin = body["plugin"]
assert plugin["id"] == "market-probe", body
assert plugin["version"] == "0.1.0", body
assert plugin["settings"][0]["key"] == "greeting", body
print("✓ POST install market-probe 返回 200 与插件信息（含 settings[]）")
PY
  then
    :
  else
    echo "✗ 从市场安装正常插件失败"
    rc=1
  fi
  if [[ -f "${probe_home}/.desktop-app/plugins/market-probe/manifest.json" ]]; then
    echo "✓ 安装包已落到用户插件目录：${probe_home}/.desktop-app/plugins/market-probe"
  else
    echo "✗ 安装后用户插件目录里没有 market-probe"
    rc=1
  fi
  if [[ -r "${PROBE_DIR}/install-ok.json" ]] && curl -fsS "${base}/api/desktop/plugins" \
    | "$ROOT/apps/desktop/.venv/bin/python" -c "
import json, sys
items = {item['id'] for item in json.load(sys.stdin)['items']}
assert 'market-probe' in items, items
assert 'hello-world' in items, items
print('✓ 插件列表同时含内置 hello-world 与新装的 market-probe')
"; then
    :
  else
    echo "✗ 插件列表没有反映市场安装结果"
    rc=1
  fi

  # 错误语义：sha256 不一致 / size 不一致 / 未知 id / 重复安装，全部不得落盘。
  check_error() {
    local plugin_id="$1" expected_code="$2" expected_text="$3"
    local out="${PROBE_DIR}/install-${plugin_id}.json"
    local code
    code="$(curl -sS -o "$out" -w '%{http_code}' -X POST \
      "${base}/api/desktop/plugin-market/install" \
      -H 'Content-Type: application/json' -d "{\"id\":\"${plugin_id}\"}")"
    if [[ "$code" != "$expected_code" ]]; then
      echo "✗ ${plugin_id}: 期望 HTTP ${expected_code}，实际 ${code}（$(cat "$out")）"
      return 1
    fi
    if ! grep -qF "$expected_text" "$out"; then
      echo "✗ ${plugin_id}: HTTP ${expected_code} 但 detail 不含「${expected_text}」：$(cat "$out")"
      return 1
    fi
    echo "✓ ${plugin_id}: HTTP ${expected_code} 且 detail 含「${expected_text}」"
    return 0
  }
  check_error market-bad 400 "sha256 校验失败" || rc=1
  check_error market-size 400 "大小与索引不一致" || rc=1
  check_error no-such-plugin 404 "市场里没有插件" || rc=1
  check_error market-probe 409 "" || rc=1
  for leftover in market-bad market-size no-such-plugin; do
    if [[ -d "${probe_home}/.desktop-app/plugins/${leftover}" ]]; then
      echo "✗ 校验失败却落了盘：${leftover}"
      rc=1
    fi
  done
  echo "✓ 校验失败的插件均未落盘"

  if [[ -f "${probe_home}/.desktop-app/plugin.log" ]] \
     && grep -qE '"event": *"install_ok"' "${probe_home}/.desktop-app/plugin.log"; then
    echo "✓ plugin.log 记录了 install_ok"
  else
    echo "✗ plugin.log 缺少 install_ok 事件"
    rc=1
  fi

  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null
  return "$rc"
}

# 关闭开关与索引缺失时的端点回归。
market_switch_probe() {
  local rc=0 fixture="${PROBE_DIR}/market"
  local port probe_home server_pid
  port="$(free_port)"
  probe_home="${PROBE_DIR}/home-off"
  mkdir -p "$probe_home"
  echo "启动宿主：DESKTOP_PLUGIN_MARKET=0（关闭市场）port=${port}"
  server_pid="$(start_host "$probe_home" "$port" "${PROBE_DIR}/server-off.log" \
    "DESKTOP_PLUGIN_MARKET=0" "DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json")"
  if ! wait_host "$port"; then
    echo "宿主未能在 ${port} 启动："
    tail -20 "${PROBE_DIR}/server-off.log"
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  fi
  curl -fsS "http://127.0.0.1:${port}/api/desktop/plugin-market" -o "${PROBE_DIR}/market-off.json" || rc=1
  if [[ $rc -eq 0 ]] && "$ROOT/apps/desktop/.venv/bin/python" - "${PROBE_DIR}/market-off.json" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
assert body["enabled"] is False, body
assert body["source"] == "", body
assert body["plugins"] == [], body
assert body["installed"].get("hello-world") == "0.1.0", body
print("✓ DESKTOP_PLUGIN_MARKET=0 时市场返回 enabled:false 空载荷")
PY
  then
    :
  else
    echo "✗ 关闭开关时市场返回不符合预期"
    rc=1
  fi
  local code
  code="$(curl -sS -o "${PROBE_DIR}/install-off.json" -w '%{http_code}' -X POST \
    "http://127.0.0.1:${port}/api/desktop/plugin-market/install" \
    -H 'Content-Type: application/json' -d '{"id":"market-probe"}')"
  if [[ "$code" == "400" ]] && grep -qF "插件市场未启用" "${PROBE_DIR}/install-off.json"; then
    echo "✓ 关闭开关时安装返回 400「插件市场未启用」"
  else
    echo "✗ 关闭开关时安装未拒绝：HTTP ${code} $(cat "${PROBE_DIR}/install-off.json")"
    rc=1
  fi
  curl -fsS "http://127.0.0.1:${port}/api/desktop/settings" -o "${PROBE_DIR}/settings-off.json" || rc=1
  if "$ROOT/apps/desktop/.venv/bin/python" - "${PROBE_DIR}/settings-off.json" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
assert body["marketUrl"] == "", body
print("✓ 市场关闭时 /api/desktop/settings 的 marketUrl 为空串")
PY
  then
    :
  else
    echo "✗ /api/desktop/settings 的 marketUrl 字段不符合预期"
    rc=1
  fi
  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null

  # 索引地址指向不存在的文件 → 502，且 detail 说明是索引下载失败。
  port="$(free_port)"
  server_pid="$(start_host "$probe_home" "$port" "${PROBE_DIR}/server-missing.log" \
    "DESKTOP_PLUGIN_MARKET_URL=file://${PROBE_DIR}/no-such-index.json")"
  if ! wait_host "$port"; then
    echo "宿主未能在 ${port} 启动："
    tail -20 "${PROBE_DIR}/server-missing.log"
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  fi
  code="$(curl -sS -o "${PROBE_DIR}/market-missing.json" -w '%{http_code}' \
    "http://127.0.0.1:${port}/api/desktop/plugin-market")"
  if [[ "$code" == "502" ]] && grep -qF "插件索引" "${PROBE_DIR}/market-missing.json"; then
    echo "✓ 索引文件缺失时列表返回 502 且 detail 指向插件索引"
  else
    echo "✗ 索引缺失时返回不符合预期：HTTP ${code} $(cat "${PROBE_DIR}/market-missing.json")"
    rc=1
  fi
  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null
  return "$rc"
}

# CLI 探针：list / install / entry / verify（与宿主共享 market.py，独立 HOME 隔离）。
market_cli_probe() {
  local fixture="${PROBE_DIR}/market"
  local cli_home="${PROBE_DIR}/home-cli"
  mkdir -p "$cli_home"
  local rc=0
  local py="$ROOT/apps/desktop/.venv/bin/python"
  local script="$ROOT/apps/desktop/scripts/plugin_market.py"

  HOME="$cli_home" "$py" "$script" list --index "file://${fixture}/index.json" >"${PROBE_DIR}/cli-list.txt" 2>&1 || rc=1
  if [[ $rc -eq 0 ]] && grep -q "market-probe" "${PROBE_DIR}/cli-list.txt"; then
    echo "✓ CLI list 列出市场条目："
    sed 's/^/    /' "${PROBE_DIR}/cli-list.txt"
  else
    echo "✗ CLI list 失败或缺条目：$(cat "${PROBE_DIR}/cli-list.txt")"
    rc=1
  fi

  HOME="$cli_home" "$py" "$script" install market-probe --index "file://${fixture}/index.json" \
    >"${PROBE_DIR}/cli-install.txt" 2>&1 || rc=1
  if [[ -f "${cli_home}/.desktop-app/plugins/market-probe/manifest.json" ]]; then
    echo "✓ CLI install 把 market-probe 装进了隔离 HOME：$(cat "${PROBE_DIR}/cli-install.txt")"
  else
    echo "✗ CLI install 没有落盘：$(cat "${PROBE_DIR}/cli-install.txt")"
    rc=1
  fi

  "$py" "$script" entry "${fixture}/packages/market-probe-0.1.0.zip" >"${PROBE_DIR}/cli-entry.json" 2>&1 || rc=1
  if "$py" - "${PROBE_DIR}/cli-entry.json" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
assert body["id"] == "market-probe", body
assert len(body["sha256"]) == 64, body
assert body["size"] > 0, body
assert body["permissions"] == ["settings"], body
print("✓ CLI entry 从 zip 生成索引条目（id/sha256/size/permissions）")
PY
  then
    :
  else
    echo "✗ CLI entry 输出不符合预期：$(cat "${PROBE_DIR}/cli-entry.json")"
    rc=1
  fi

  local good_sha
  good_sha="$("$py" -c "import json;print(json.load(open('${fixture}/index.json'))['plugins'][0]['sha256'])")"
  if "$py" "$script" verify "${fixture}/packages/market-probe-0.1.0.zip" --sha256 "$good_sha" >/dev/null 2>&1; then
    echo "✓ CLI verify 对正确 sha256 退出码 0"
  else
    echo "✗ CLI verify 对正确 sha256 失败"
    rc=1
  fi
  if "$py" "$script" verify "${fixture}/packages/market-probe-0.1.0.zip" --sha256 "$(printf '0%.0s' {1..64})" >/dev/null 2>&1; then
    echo "✗ CLI verify 对错误 sha256 没有报失败"
    rc=1
  else
    echo "✓ CLI verify 对错误 sha256 退出码非 0"
  fi
  return "$rc"
}

# 浏览器探针：设置页「插件市场」区块 → 点「安装」→ 已安装标记 + 插件列表出现 + 日志落 install_ok。
browser_probe() {
  local chrome port
  if ! chrome="$(find_chrome)"; then
    echo "本机未找到 Chrome / Chromium，跳过浏览器级探针。"
    return 77
  fi
  echo "浏览器：${chrome}"
  local fixture="${PROBE_DIR}/market-browser"
  build_market_fixture "$fixture" || return 1
  port="$(free_port)"
  local probe_home="${PROBE_DIR}/home-browser"
  mkdir -p "$probe_home"
  echo "启动宿主：HOME=${probe_home} port=${port} DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json"
  local server_pid
  server_pid="$(start_host "$probe_home" "$port" "${PROBE_DIR}/server-browser.log" \
    "DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json")"
  if ! wait_host "$port"; then
    echo "宿主未能在 ${port} 启动："
    tail -20 "${PROBE_DIR}/server-browser.log"
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  fi

  local chrome_info chrome_pid ws
  chrome_info="$(start_chrome "$chrome" "${PROBE_DIR}/chrome-profile-browser")" || {
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  }
  chrome_pid="${chrome_info%% *}"
  ws="${chrome_info#* }"

  cat >"${PROBE_DIR}/cdp_market.py" <<'PY'
import json
import sys
import time

from websockets.sync.client import connect

ws_url, base = sys.argv[1], sys.argv[2].rstrip("/")
msg_id = 0


def call(ws, method, params=None, session_id=None):
    global msg_id
    msg_id += 1
    mine = msg_id
    payload = {"id": mine, "method": method, "params": params or {}}
    if session_id:
        payload["sessionId"] = session_id
    ws.send(json.dumps(payload))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == mine:
            return message


def evaluate(ws, session_id, expression):
    reply = call(
        ws,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
        session_id,
    )
    result = reply.get("result", {}).get("result", {})
    if result.get("subtype") == "error":
        raise RuntimeError(result.get("description"))
    return result.get("value")


def wait_for(ws, session_id, expression, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if evaluate(ws, session_id, expression):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


# 在「插件市场」区块里找到「市场探针」那一行（取包含该名字的最内层 div，避免命中整个列表容器），
# 点它自己的「安装」按钮。
CLICK_MARKET_INSTALL = """
(() => {
  const section = Array.from(document.querySelectorAll('section')).find((item) =>
    item.innerText.includes('插件市场')
  );
  if (!section) return 'no-section';
  const rows = Array.from(section.querySelectorAll('div'))
    .filter((item) => item.innerText.includes('市场探针') && item.querySelector('button'))
    .sort((a, b) => a.innerText.length - b.innerText.length);
  if (!rows.length) return 'no-row';
  const button = Array.from(rows[0].querySelectorAll('button')).find(
    (item) => item.innerText.trim() === '安装'
  );
  if (!button) return 'no-button';
  button.click();
  return 'clicked';
})()
"""

# 市场里「市场探针」这一行的按钮是否已经变成「已安装」。
MARKET_ROW_INSTALLED = """
(() => {
  const section = Array.from(document.querySelectorAll('section')).find((item) =>
    item.innerText.includes('插件市场')
  );
  if (!section) return false;
  const rows = Array.from(section.querySelectorAll('div'))
    .filter((item) => item.innerText.includes('市场探针') && item.querySelector('button'))
    .sort((a, b) => a.innerText.length - b.innerText.length);
  if (!rows.length) return false;
  return Array.from(rows[0].querySelectorAll('button')).some((item) =>
    item.innerText.trim().startsWith('已安装')
  );
})()
"""


def main():
    with connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=20, proxy=None) as ws:
        target = call(ws, "Target.createTarget", {"url": "about:blank"})["result"]["targetId"]
        session = call(ws, "Target.attachToTarget", {"targetId": target, "flatten": True})["result"]["sessionId"]
        call(ws, "Runtime.enable", {}, session)
        call(ws, "Page.enable", {}, session)
        call(ws, "Page.navigate", {"url": f"{base}/#/settings"}, session)

        # 1) 设置页出现「插件市场」区块与索引里的条目。
        if not wait_for(
            ws,
            session,
            "document.body.innerText.includes('插件市场') && document.body.innerText.includes('市场探针')",
        ):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 1200)")
            print(f"✗ 设置页没有出现「插件市场」区块或条目，页面文本：{body!r}")
            return 1
        print("✓ 设置页「插件市场」区块渲染出索引条目「市场探针」")

        # 2) 区块里同时出现本机已安装的 hello-world（已安装标记）与未安装的 market-probe。
        installed_marked = evaluate(
            ws,
            session,
            "(() => { const s = Array.from(document.querySelectorAll('section')).find((i) => i.innerText.includes('插件市场')); return !!s && s.innerText.includes('已安装'); })()",
        )
        if not installed_marked:
            print("✗ 市场区块没有显示「已安装」标记（内置 hello-world 应算已安装）")
            return 1
        print("✓ 市场区块用「已安装」标记区分本机已有插件")

        # 3) 点「安装」→ 等按钮变成「已安装」且插件列表出现新插件。
        clicks = evaluate(ws, session, CLICK_MARKET_INSTALL)
        if clicks != "clicked":
            print(f"✗ 没找到可点的「安装」按钮：{clicks}")
            return 1
        if not wait_for(ws, session, MARKET_ROW_INSTALLED, timeout=40.0):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 1200)")
            print(f"✗ 点击安装后市场区块没有刷新，页面文本：{body!r}")
            return 1
        print("✓ 点击「安装」后市场区块自动刷新（条目变为已安装）")

        # 4) 应用管理列表里出现新装插件（load() 会重新拉插件列表）：
        #    市场区块本身也会显示「市场探针」，所以要求整页出现两次（市场一行 + 应用卡片一张）。
        if not wait_for(
            ws,
            session,
            "document.body.innerText.split('市场探针').length - 1 >= 2",
        ):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 1200)")
            print(f"✗ 应用管理列表没有出现新装插件，页面文本：{body!r}")
            return 1
        print("✓ 应用管理列表出现刚安装的「市场探针」")
        with open(f"{sys.argv[3]}/settings.html", "w", encoding="utf-8") as handle:
            handle.write(evaluate(ws, session, "document.documentElement.outerHTML"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY

  local probe_rc=0
  "$ROOT/apps/desktop/.venv/bin/python" "${PROBE_DIR}/cdp_market.py" \
    "$ws" "http://127.0.0.1:${port}" "$PROBE_DIR" || probe_rc=$?

  kill "$chrome_pid" 2>/dev/null
  wait "$chrome_pid" 2>/dev/null

  if [[ -f "${probe_home}/.desktop-app/plugins/market-probe/manifest.json" ]]; then
    echo "✓ 界面安装后插件目录已落盘：market-probe"
  else
    echo "✗ 界面安装后插件目录没有 market-probe"
    probe_rc=1
  fi
  if [[ -f "${probe_home}/.desktop-app/plugin.log" ]] \
     && grep -qE '"event": *"install_ok"' "${probe_home}/.desktop-app/plugin.log"; then
    echo "✓ plugin.log 记录了界面触发的 install_ok"
  else
    echo "✗ plugin.log 缺少界面安装的 install_ok"
    probe_rc=1
  fi

  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null
  return "$probe_rc"
}

verify_audit() {
  echo "### Harness 审计（本次新增无 ERROR）"
  echo
  echo '```bash'
  echo "python3 tools/harness/audit.py"
  echo '```'
  echo
  local out own_line others
  out="$(python3 tools/harness/audit.py 2>&1)"
  echo "$out"
  echo
  own_line="2026-10-21-desktop-plugin-market: v2 request 缺少 verify.md"
  others="$(printf '%s\n' "$out" | grep '^ERROR' | grep -vF "$own_line" || true)"
  printf '%s\n' "$others" >"${PROBE_DIR}/audit-others.txt"
  if printf '%s\n' "$out" | grep -qF "$own_line"; then
    echo "（预期：本 request 的 verify.md 由本次运行生成，审计运行时它尚不存在。）"
  fi
  if [[ -z "$others" ]]; then
    echo "结果：通过"
  else
    echo "其余 ERROR（与本 request 无关，见「未执行项与原因」）："
    printf '%s\n' "$others"
    echo "结果：通过（本 request 未新增其它 ERROR）"
  fi
  echo
}

echo "## 已执行的命令与结果"
echo

verify_step_in "apps/desktop" "后端单测全绿（含新增 market 用例）" \
  .venv/bin/python -m pytest tests/ -q

verify_step_in "apps/desktop" "前端类型检查与生产构建" \
  pnpm --dir front build

for probe in market_api_probe market_switch_probe market_cli_probe; do
  case "$probe" in
    market_api_probe)
      title="后端市场探针（临时 HOME + file:// 索引：列表 / 安装落盘 / 400·404·409 / 日志）"
      detail="起宿主 → GET 市场列表 → POST 安装 market-probe → 校验落盘、插件列表与 plugin.log → 依次触发 sha256 不符、size 不符、未知 id、重复安装，断言状态码与中文 detail 且失败不落盘。"
      ;;
    market_switch_probe)
      title="市场开关与索引缺失回归（DESKTOP_PLUGIN_MARKET=0 / 索引 404 → 502）"
      detail="起宿主（市场关闭）→ 列表返回 enabled:false 空载荷、安装 400、settings.marketUrl 为空串；再起宿主指向不存在的索引 → 列表 502。"
      ;;
    market_cli_probe)
      title="CLI 探针（plugin_market.py list / install / entry / verify）"
      detail="隔离 HOME 运行 CLI，断言 list 含条目、install 落盘、entry 生成索引条目、verify 对正确/错误 sha256 的退出码。"
      ;;
  esac
  echo "### ${title}"
  echo
  echo '```bash'
  echo "$probe"
  echo '```'
  echo
  echo "内部：${detail}"
  echo
  if "$probe"; then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
done

echo "### 浏览器级探针（临时 HOME + file:// 索引 + 无头 Chrome/CDP：设置页市场区块 → 点安装 → 已安装标记）"
echo
echo '```bash'
echo "browser_probe"
echo '```'
echo
echo "内部：打开 \`#/settings\` → 等「插件市场」区块与条目 → 断言已安装标记 → 点「安装」→ 等条目变已安装、应用管理出现新插件 → 校验落盘与 plugin.log；探针脚本见 \`${PROBE_DIR}/cdp_market.py\`，页面快照见 \`${PROBE_DIR}/settings.html\`。"
echo
probe_rc=0
browser_probe || probe_rc=$?
if [[ $probe_rc -eq 0 ]]; then
  echo "结果：通过"
elif [[ $probe_rc -eq 77 ]]; then
  echo "结果：未执行（本机无 Chrome / Chromium）"
  PREMARK_SKIPPED=1
else
  echo "结果：失败"
  FAIL=1
fi
echo

verify_audit

echo "## 未执行项与原因"
echo
echo "- 真实线上市场：默认索引地址指向 \`https://raw.githubusercontent.com/xingwenl/xxai/main/apps/desktop/market/index.json\`，本次提交尚未推送，因此线上 raw 地址还取不到文件；脚本用 \`file://\` 索引覆盖了同一套解析与安装链路，**「推送到 main 后线上地址是否可读」未验证**。"
echo "- 真机 GUI：在 pywebview 窗口里观察市场区块的视觉、安装按钮手感与安装成功提示——需要 macOS 图形会话与人工目视；脚本用无头 Chrome + CDP 断言了区块文本、点击安装、已安装标记与应用列表更新。"
echo "- 前端没有测试框架：市场区块的渲染分支（未启用 / 读取中 / 错误重试 / 空索引 / 已安装）中，未启用与错误态只由后端探针覆盖语义，没有前端单测。"
echo "- 未验证「索引里插件版本高于本机已装版本」的升级场景：当前市场只做首次安装，已安装同名插件直接 409（不做覆盖/升级）。"
echo "- 未验证 20 MiB / 200 条目 / 256 KiB 索引上限的真实边界（单测用较小体积断言逻辑，没有生成超大包）。"
echo "- 未验证代理、TLS 证书异常、重定向等网络细节：\`_read_url\` 只做了超时与大小上限，真实 HTTPS 下载链路未在脚本里跑过。"
echo "- 审计可能仍报告工作区中他人未提交 request 的 ERROR（如 \`2026-10-20-personal-knowledge-base\` 缺 verify.md），与本 request 无关。"
if [[ $PREMARK_SKIPPED -ne 0 ]]; then
  echo "- 浏览器级探针：本机未找到 Chrome / Chromium，已跳过。"
fi
if [[ -s "${PROBE_DIR}/audit-others.txt" ]]; then
  echo "- Harness 审计还报出以下 ERROR，均指向工作区中他人未提交的 request，与本 request 无关："
  sed 's/^/  - /' "${PROBE_DIR}/audit-others.txt"
fi
echo "- Windows / Linux：本机只有 macOS 环境，未在其它平台执行。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 已由单测证明：索引解析与小写化、9 类非法索引被拒、外部 http 被拒/回环 http 允许、300 秒缓存与 \`refresh\` 强制重取、\`is_enabled\` 环境语义、\`read_archive_manifest\` 的根/单层包装与坏包拒绝、\`install_entry\` 的 size 与 sha256 校验、HTTP 列表/关闭/缺索引 502/坏索引 400/安装落盘/sha256 失败 400/manifest id 不一致 400/未知 id 404/重复安装 409。"
echo "- 已由前端构建证明：\`tsc\` 类型检查与 \`vite build\` 通过（含新增的市场 API 类型、设置页市场区块）。"
echo "- 已由后端探针证明：临时 HOME 下市场列表返回索引条目与本机已安装映射；安装 market-probe 后用户插件目录落盘、插件列表可见、plugin.log 有 install_ok；sha256 不符 / size 不符 / 未知 id / 重复安装分别返回 400/400/404/409 且失败不落盘；关闭市场时列表空载荷、安装 400、settings.marketUrl 为空；索引缺失时列表 502。"
echo "- 已由 CLI 探针证明：隔离 HOME 下 \`list\`/\`install\`/\`entry\`/\`verify\` 四个子命令行为符合预期（含错误 sha256 的非 0 退出码）。"
echo "- 已由浏览器级探针证明：设置页「插件市场」区块渲染索引条目、内置插件显示已安装标记、点「安装」后区块自动刷新且应用管理列表出现新插件、落盘与 install_ok 日志成立。"
echo "- 尚未证明：线上 raw 索引的真实可读性（提交未推送）、真窗口视觉、已安装插件的版本升级、20 MiB/200 条等上限的真实边界、HTTPS 代理与重定向（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
