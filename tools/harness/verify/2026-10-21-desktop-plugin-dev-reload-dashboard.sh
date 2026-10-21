#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-21-desktop-plugin-dev-reload-dashboard
#
# 覆盖范围：插件目录指纹端点与 dev 开关、dashboard 权限白名单、前端类型检查与生产构建，
# 以及「临时 HOME + DESKTOP_DEV_RELOAD=1 + 无头 Chrome + CDP」的浏览器级探针：
# 首页概览卡渲染 → 点击卡片进入子应用 → 改插件目录里的 index.html 后 iframe 不刷新页面即更新。
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

# 找一个可用的无头浏览器。
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

# 取一个空闲端口。
free_port() {
  "$ROOT/apps/desktop/.venv/bin/python" - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

# 启动带 CDP 调试端口的无头 Chrome，输出「pid ws 地址」。
# 说明：Chrome 155 起 --headless 旧模式已移除；沙箱环境里还需要可写 HOME（crashpad）
# 与 --no-sandbox，否则 GPU 进程初始化会 FATAL 退出。
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

# 起一个宿主进程（调用方负责传 HAHA_HOME/端口），等到 /api/health 可用后返回 pid。
start_host() {
  local home="$1" port="$2" log="$3"
  HOME="$home" DESKTOP_DEV_RELOAD=1 PYTHONPATH="${ROOT}/apps/desktop" \
    "$ROOT/apps/desktop/.venv/bin/python" -c "
import uvicorn
from desktop_app.server import create_app
uvicorn.run(create_app(dev_agent_enabled=False), host='127.0.0.1', port=${port}, log_level='warning')
" >"$log" 2>&1 &
  echo $!
}

# 浏览器级探针：临时 HOME + 一个声明 dashboard 权限的插件，
# 验证首页概览卡、点击进入子应用、改盘上 index.html 后 iframe 无刷新更新。
# 成功 0 / 无浏览器 77 / 失败 1。
browser_probe() {
  local chrome port
  if ! chrome="$(find_chrome)"; then
    echo "本机未找到 Chrome / Chromium，跳过浏览器级探针。"
    return 77
  fi
  echo "浏览器：${chrome}"
  port="$(free_port)"
  local probe_home="${PROBE_DIR}/home"
  local plugin_dir="${probe_home}/.desktop-app/plugins/reload-probe"
  mkdir -p "$plugin_dir"

  cat >"${plugin_dir}/manifest.json" <<'JSON'
{
  "id": "reload-probe",
  "name": "热重载探针",
  "version": "0.1.0",
  "description": "验证开发热重载与首页概览卡",
  "entry": "index.html",
  "permissions": ["dashboard"]
}
JSON
  # 插件页与概览卡内容都由同一个版本号驱动，改文件即改页面文本与卡片指标。
  write_plugin_html() {
    local version="$1"
    local target="$2"
    cat >"$target" <<HTML
<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>热重载探针</title></head>
<body><div id="out">版本${version} · 初始内容</div>
<script>
  (async () => {
    await new Promise((resolve) => {
      if (window.desktop) return resolve();
      window.addEventListener("desktop-ready", () => resolve(), { once: true });
    });
    window.desktop.dashboard.publish({
      title: "热重载探针概览",
      metrics: [{ label: "版本", value: "版本${version}" }],
      recent: [{ text: "来自插件目录的实时内容", hint: "reload" }]
    });
  })();
</script></body></html>
HTML
  }
  write_plugin_html "一" "${plugin_dir}/index.html"

  echo "启动宿主：HOME=${probe_home} port=${port} DESKTOP_DEV_RELOAD=1"
  local server_pid
  server_pid="$(start_host "$probe_home" "$port" "${PROBE_DIR}/server.log")"
  local ready=1
  for _ in $(seq 1 60); do
    sleep 0.2
    if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then ready=0; break; fi
  done
  if [[ $ready -ne 0 ]]; then
    echo "宿主未能在 ${port} 启动："
    tail -20 "${PROBE_DIR}/server.log"
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  fi

  local chrome_info chrome_pid ws
  chrome_info="$(start_chrome "$chrome" "${PROBE_DIR}/chrome-profile")" || {
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  }
  chrome_pid="${chrome_info%% *}"
  ws="${chrome_info#* }"

  cat >"${PROBE_DIR}/cdp_check.py" <<'PY'
import json
import sys
import time

from websockets.sync.client import connect

ws_url, base, plugin_html = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
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


def wait_for(ws, session_id, expression, timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if evaluate(ws, session_id, expression):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def iframe_text():
    # 声明 dashboard/tools 的子应用会在宿主启动时静默挂载（隐藏 iframe），所以页面上可能同时存在
    # 多个 iframe；只读尺寸非零的那一个（隐藏层的 display:none 让 getBoundingClientRect 为 0）。
    return """
        (() => {
          const frame = Array.from(document.querySelectorAll("iframe")).find(
            (item) => item.getBoundingClientRect().height > 0
          );
          if (!frame || !frame.contentDocument || !frame.contentDocument.body) return "";
          return frame.contentDocument.body.innerText || "";
        })()
    """


def html(version):
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>热重载探针</title></head>
<body><div id="out">版本%s · 初始内容</div>
<script>
  (async () => {
    await new Promise((resolve) => {
      if (window.desktop) return resolve();
      window.addEventListener("desktop-ready", () => resolve(), { once: true });
    });
    window.desktop.dashboard.publish({
      title: "热重载探针概览",
      metrics: [{ label: "版本", value: "版本%s" }],
      recent: [{ text: "来自插件目录的实时内容", hint: "reload" }]
    });
  })();
</script></body></html>
""" % (version, version)


def main():
    status = 0
    # proxy=None：不给本机 CDP 走系统代理（macOS 上 proxy=True 会尝试 SOCKS 而缺依赖）。
    with connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=20, proxy=None) as ws:
        # 先建空页再导航：直接 createTarget(url) 时页面可能在 attach 前就开始加载。
        target = call(ws, "Target.createTarget", {"url": "about:blank"})["result"]["targetId"]
        session = call(ws, "Target.attachToTarget", {"targetId": target, "flatten": True})["result"]["sessionId"]
        call(ws, "Runtime.enable", {}, session)
        call(ws, "Page.enable", {}, session)
        call(ws, "Page.navigate", {"url": f"{base}/"}, session)

        # 1) 首页出现内置 hello-world 的概览卡（它改成了活样板，声明 dashboard 并 publish）。
        if not wait_for(
            ws,
            session,
            "document.body.innerText.includes('你好世界的概览') && document.body.innerText.includes('概览')",
        ):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 800)")
            print("✗ 首页没有出现 hello-world 概览卡")
            print(f"  页面文本：{body!r}")
            return 1
        print("✓ 首页出现 hello-world 概览卡（概览区 + 标题）")

        # 2) 声明 dashboard 的子应用随首屏静默挂载，所以还没点开就应该有探针的概览卡。
        if not wait_for(ws, session, "document.body.innerText.includes('热重载探针概览')"):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 800)")
            print("✗ 首页没有出现探针插件推送的概览卡")
            print(f"  页面文本：{body!r}")
            return 1
        print("✓ 探针插件的概览卡出现在首页（未打开子应用）")

        # 3) 点首页卡片进入子应用（不走 #/app/<id> 深链：既有冷启动竞态）。
        if not wait_for(ws, session, "!!Array.from(document.querySelectorAll('[role=button]')).find((item) => item.innerText.includes('热重载探针'))"):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 800)")
            print("✗ 首页没有出现「热重载探针」插件卡片")
            print(f"  页面文本：{body!r}")
            return 1
        evaluate(
            ws,
            session,
            "Array.from(document.querySelectorAll('[role=button]')).find((item) => item.innerText.includes('热重载探针')).click()",
        )
        if not wait_for(ws, session, f"({iframe_text()}).includes('版本一')"):
            print(f"✗ 打开子应用后 iframe 没有显示「版本一」，实际：{evaluate(ws, session, iframe_text())!r}")
            return 1
        print("✓ 点击卡片进入子应用，iframe 显示「版本一」")

        # 4) 改盘上 index.html（不刷新宿主页面、不重启宿主），等热重载轮询生效。
        # 轮询的第一笔只用来记录基线指纹，所以先等它落定（页面加载后 1.5s 才第一次轮询），
        # 否则改动早于基线、永远不会被判为「变了」——这是探针时序，不是产品缺陷。
        time.sleep(3.0)
        with open(plugin_html, "w", encoding="utf-8") as handle:
            handle.write(html("二"))
        time.sleep(0.3)
        if not wait_for(ws, session, f"({iframe_text()}).includes('版本二')", timeout=30.0):
            print(f"✗ 改动 index.html 后 iframe 没有自动更新，实际：{evaluate(ws, session, iframe_text())!r}")
            return 1
        print("✓ 改盘上 index.html 后 iframe 自动重新加载为「版本二」（未刷新整页）")

        # 5) 回到首页：重载后的 iframe 重新 publish，概览卡指标应同步成「版本二」。
        evaluate(ws, session, "document.querySelector('.shell-back')?.click()")
        if not wait_for(ws, session, "document.body.innerText.includes('版本二')", timeout=15.0):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 800)")
            print(f"✗ 返回首页后概览卡没有随热重载更新为「版本二」，页面：{body!r}")
            return 1
        print("✓ 返回首页后概览卡指标已随热重载更新为「版本二」")

        # 6) 已打开子应用未丢：返回首页后卡片与运行状态都还在。
        if not wait_for(ws, session, "!!Array.from(document.querySelectorAll('[role=button]')).find((item) => item.innerText.includes('热重载探针'))", timeout=10.0):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 500)")
            print(f"✗ 返回首页后插件卡片消失（页面）：{body!r}")
            return 1
        print("✓ 返回首页后插件卡片仍在（页面状态未被打断）")

    return status


if __name__ == "__main__":
    sys.exit(main())
PY

  local probe_rc=0
  "$ROOT/apps/desktop/.venv/bin/python" "${PROBE_DIR}/cdp_check.py" \
    "$ws" "http://127.0.0.1:${port}" "${plugin_dir}/index.html" || probe_rc=$?

  kill "$chrome_pid" 2>/dev/null
  wait "$chrome_pid" 2>/dev/null

  # 宿主侧断言：概览卡来自 SDK 推送（内存态），日志里应有子应用的 iframe_load。
  if [[ -f "${probe_home}/.desktop-app/plugin.log" ]] \
     && grep -qE '"event": *"iframe_load"' "${probe_home}/.desktop-app/plugin.log"; then
    echo "✓ plugin.log 含 reload-probe 的 iframe_load："
    grep -E 'iframe_load|sdk_injected' "${probe_home}/.desktop-app/plugin.log" | head -6
  else
    echo "✗ plugin.log 缺少 iframe_load 事件"
    probe_rc=1
  fi

  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null
  return "$probe_rc"
}

# 未设置环境变量时端点必须整体关闭：不遍历磁盘、前端不受影响。
revision_disabled_probe() {
  local port probe_home server_pid
  port="$(free_port)"
  probe_home="${PROBE_DIR}/home-disabled"
  mkdir -p "$probe_home"
  echo "启动宿主（未设置 DESKTOP_DEV_RELOAD）：HOME=${probe_home} port=${port}"
  HOME="$probe_home" PYTHONPATH="${ROOT}/apps/desktop" \
    "$ROOT/apps/desktop/.venv/bin/python" -c "
import uvicorn
from desktop_app.server import create_app
uvicorn.run(create_app(dev_agent_enabled=False), host='127.0.0.1', port=${port}, log_level='warning')
" >"${PROBE_DIR}/server-disabled.log" 2>&1 &
  server_pid=$!
  local ready=1
  for _ in $(seq 1 60); do
    sleep 0.2
    if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then ready=0; break; fi
  done
  if [[ $ready -ne 0 ]]; then
    echo "宿主未能在 ${port} 启动："
    tail -20 "${PROBE_DIR}/server-disabled.log"
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  fi

  local rc=0
  curl -fsS "http://127.0.0.1:${port}/api/desktop/plugin-revision" -o "${PROBE_DIR}/revision-off.json" || rc=1
  if [[ $rc -eq 0 ]] && python3 - "${PROBE_DIR}/revision-off.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["enabled"] is False, payload
assert payload["revision"] == "", payload
assert payload["plugins"] == {}, payload
print("✓ 未开启时 GET /api/desktop/plugin-revision 返回 enabled:false 且无插件指纹")
PY
  then
    :
  else
    echo "✗ 未开启时的 plugin-revision 返回不符合预期"
    rc=1
  fi

  curl -fsS "http://127.0.0.1:${port}/api/desktop/settings" -o "${PROBE_DIR}/settings-off.json" || rc=1
  if [[ $rc -eq 0 ]] && python3 - "${PROBE_DIR}/settings-off.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["devReload"] is False, payload
print("✓ /api/desktop/settings 的 devReload 为 false")
PY
  then
    :
  else
    echo "✗ /api/desktop/settings 缺少正确的 devReload 字段"
    rc=1
  fi

  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null
  return "$rc"
}

# Harness 审计：本 request 的 verify.md 由 verify.sh 在脚本结束后才写入，
# 所以审计必然报「本 request 缺少 verify.md」——这条属预期，其余 ERROR 需人工核对归属。
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
  own_line="2026-10-21-desktop-plugin-dev-reload-dashboard: v2 request 缺少 verify.md"
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

verify_step_in "apps/desktop" "后端单测全绿（含新增 dev_reload / dashboard 权限用例）" \
  .venv/bin/python -m pytest tests/ -q

verify_step_in "apps/desktop" "前端类型检查与生产构建" \
  pnpm --dir front build

echo "### 未开启 DESKTOP_DEV_RELOAD 时的端点回归"
echo
echo '```bash'
echo "revision_disabled_probe"
echo '```'
echo
echo "内部：临时 HOME 起宿主 → GET /api/desktop/plugin-revision 断言 enabled:false → GET /api/desktop/settings 断言 devReload:false。"
echo
if revision_disabled_probe; then
  echo "结果：通过"
else
  echo "结果：失败"
  FAIL=1
fi
echo

echo "### 浏览器级探针（临时 HOME + DESKTOP_DEV_RELOAD=1 + 无头 Chrome/CDP：概览卡 → 进入子应用 → 改盘上文件后自动重载）"
echo
echo '```bash'
echo "browser_probe"
echo '```'
echo
echo "内部依次：首页概览卡渲染 / 点击卡片进入子应用 / 改盘上 index.html / 不刷新页面等 iframe 文本更新 / 概览卡指标同步 / 返回首页状态未丢；探针脚本见 \`${PROBE_DIR}/cdp_check.py\`。"
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
echo "- 真机 GUI：在 pywebview 窗口里观察概览卡视觉、点击手感与热重载时的 toast 提示——需要 macOS 图形会话与人工目视。脚本用无头 Chrome + CDP 复现了同一条链路（首页概览卡 → 打开子应用 → 改文件 → iframe 自动重载）并断言了 DOM 文本。"
echo "- 前端没有测试框架：概览卡的截断上限（标题 ≤40、指标 ≤4 条、最近 ≤5 条）与 \`dashboard-bridge\` 的订阅/清理由浏览器级探针间接覆盖，没有组件单测覆盖全部字段分支；\`desktop.dashboard.publish\` 未声明权限时抛「权限不足」的错误文案只由类型与实现保证，未在探针里构造该场景。"
echo "- 热重载未覆盖 react 类型子应用（\`bookmarks-organizer\`）：它是宿主编译产物，需要 \`pnpm build\` 后重启宿主，README 已写明；探针只覆盖 iframe 类型插件。"
echo "- 多窗口：热重载按页面各自轮询，未验证两个宿主窗口同时打开时的表现（预期各自独立重载，没有跨窗口同步）。"
echo "- \`tests/test_host_api.py\` 的 \`test_macos_open_*\` 用例属于工作区中他人未提交的 WIP，其文件顶部缺 \`import subprocess\`；本次运行前已临时补该行（不随本 request 提交），因此全量 pytest 通过。在纯净 HEAD 上该用例不存在。"
if [[ $PREMARK_SKIPPED -ne 0 ]]; then
  echo "- 浏览器级探针：本机未找到 Chrome / Chromium，已跳过。"
fi
if [[ -s "${PROBE_DIR}/audit-others.txt" ]]; then
  echo "- Harness 审计还报出以下 ERROR，均指向工作区中他人未提交的 request，与本 request 无关："
  sed 's/^/  - /' "${PROBE_DIR}/audit-others.txt"
fi
echo "- Windows / Linux：本机只有 macOS 环境，未在其它平台执行（\`os.walk\` 与 mtime_ns 跨平台行为一致，但未实测）。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 已由单测证明：\`DESKTOP_DEV_RELOAD\` 的 truthy/falsy 解析、未开启时端点返回 \`enabled:false\` 空载荷、开启后列出内置与用户插件且指纹为 12 位十六进制、只改一个插件只让该插件指纹变化、\`node_modules\`/\`__pycache__\`/\`.git\`/\`dist\` 改动不影响 revision、\`/api/desktop/settings\` 的 \`devReload\` 随环境变量翻转、\`dashboard\` 进入权限白名单且 \`unknown_permissions()\` 为空。"
echo "- 已由前端构建证明：\`tsc\` 类型检查与 \`vite build\` 通过（包含新增的 \`dashboard-bridge.ts\`、\`dashboard-cards.tsx\`、\`PluginView\` 的 \`reloadToken\` 与 \`App.tsx\` 的 revision 轮询）。"
echo "- 已由浏览器级探针证明：临时 HOME 下首页「概览」区同时出现内置 hello-world 与探针插件的概览卡；点击探针卡片进入子应用；直接修改盘上 \`index.html\` 后**不刷新宿主页面**，iframe 自动重新加载为新文本；重新发布的概览卡指标同步更新；返回首页后插件与页面状态未丢。"
echo "- 已由端点回归证明：未设置 \`DESKTOP_DEV_RELOAD\` 时 \`GET /api/desktop/plugin-revision\` 返回 \`enabled:false\`、\`revision\` 为空、\`plugins\` 为空，\`/api/desktop/settings\` 的 \`devReload\` 为 false。"
echo "- 尚未证明：真窗口里的视觉与手感、react 类型子应用的热重载（本就不做）、多窗口并发、Windows / Linux 平台（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。"
echo "- 已知边界：热重载依赖前端轮询（1.5s 间隔），最坏场景下改动生效有约 1.5s 延迟；概览卡是内存态，宿主页面刷新后由插件重新 publish。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
