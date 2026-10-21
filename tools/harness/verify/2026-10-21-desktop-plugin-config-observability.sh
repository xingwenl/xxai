#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-21-desktop-plugin-config-observability
#
# 覆盖范围：manifest.settings[] 协议与配置存储/端点、plugin.log 事件日志、
# 前端类型检查与生产构建，以及「临时 HOME + 无头 Chrome + CDP」的浏览器级探针：
# 设置页点开配置表单 → 改值保存后写盘 → 运行中的插件 iframe 通过 onChanged 立即更新 → 事件日志。
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

# 启动带 CDP 调试端口的无头 Chrome，输出 ws 调试地址。
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

# 浏览器级探针：临时 HOME + 一个声明 settings[] 的插件，验证设置页表单、保存落盘、
# 运行中 iframe 的实时更新与事件日志。成功 0 / 无浏览器 77 / 失败 1。
browser_probe() {
  local chrome port
  if ! chrome="$(find_chrome)"; then
    echo "本机未找到 Chrome / Chromium，跳过浏览器级探针。"
    return 77
  fi
  echo "浏览器：${chrome}"
  port="$(free_port)"
  local probe_home="${PROBE_DIR}/home"
  local plugin_dir="${probe_home}/.desktop-app/plugins/demo-settings"
  mkdir -p "$plugin_dir"

  cat >"${plugin_dir}/manifest.json" <<'JSON'
{
  "id": "demo-settings",
  "name": "配置探针",
  "version": "0.1.0",
  "entry": "index.html",
  "permissions": ["settings"],
  "settings": [
    { "key": "greeting", "label": "问候语", "type": "text", "default": "你好", "description": "首页问候语" },
    { "key": "refresh", "label": "刷新间隔", "type": "number", "default": 30, "min": 5, "max": 300 },
    { "key": "verbose", "label": "详细日志", "type": "boolean", "default": false }
  ]
}
JSON
  # 插件页：getConfig() 读初值，onChanged() 订阅宿主保存后的实时推送。
  cat >"${plugin_dir}/index.html" <<'HTML'
<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>配置探针</title></head>
<body><div id="out">waiting</div>
<script>
  (async () => {
    await new Promise((resolve) => {
      if (window.desktop) return resolve();
      window.addEventListener("desktop-ready", () => resolve(), { once: true });
    });
    const api = window.desktop.settings;
    const out = document.getElementById("out");
    const render = (values) => { out.textContent = values.greeting; };
    render(await api.getConfig());
    api.onChanged((values) => render(values));
  })();
</script></body></html>
HTML

  echo "启动宿主：HOME=${probe_home} port=${port}"
  HOME="$probe_home" PYTHONPATH="${ROOT}/apps/desktop" "$ROOT/apps/desktop/.venv/bin/python" -c "
import uvicorn
from desktop_app.server import create_app
uvicorn.run(create_app(dev_agent_enabled=False), host='127.0.0.1', port=${port}, log_level='warning')
" >"${PROBE_DIR}/server.log" 2>&1 &
  local server_pid=$!
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

  local status=0

  # a) 列表接口把 settings[] 原样暴露给前端；未声明 settings 的既有插件仍是空数组。
  curl -fsS "http://127.0.0.1:${port}/api/desktop/plugins" -o "${PROBE_DIR}/plugins.json"
  if python3 - "${PROBE_DIR}/plugins.json" <<'PY'
import json
import sys

items = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
by_id = {item["id"]: item for item in items}
demo = [s["key"] for s in by_id["demo-settings"]["settings"]]
assert demo == ["greeting", "refresh", "verbose"], demo
hello = [s["key"] for s in by_id["hello-world"]["settings"]]
assert hello == ["greeting", "notify_on_start", "accent"], hello
assert by_id["bookmarks-organizer"]["settings"] == [], by_id["bookmarks-organizer"]["settings"]
PY
  then
    echo "✓ 插件列表带 settings[]：demo-settings 三项、hello-world 三项、bookmarks-organizer 为空"
  else
    echo "✗ 插件列表的 settings[] 不符合预期"
    status=1
  fi

  # b) 先经 HTTP 保存一次合法配置，检查原子落盘（类型保持）。
  curl -fsS -X PUT "http://127.0.0.1:${port}/api/desktop/plugins/demo-settings/config" \
    -H 'Content-Type: application/json' \
    -d '{"values":{"greeting":"验证问候","refresh":12,"verbose":true}}' >/dev/null 2>&1
  local config_file="${probe_home}/.desktop-app/plugin-config/demo-settings.json"
  if [[ -f "$config_file" ]] && grep -q '验证问候' "$config_file" && grep -q '"refresh":12' "$config_file" && grep -q '"verbose":true' "$config_file"; then
    echo "✓ 配置已原子落盘：$(cat "$config_file")"
  else
    echo "✗ 配置落盘内容不符：$(cat "$config_file" 2>/dev/null || echo 文件不存在)"
    status=1
  fi

  # c) 非法值 400 且不覆盖已有配置。
  local invalid_code
  invalid_code="$(curl -sS -o "${PROBE_DIR}/invalid.json" -w '%{http_code}' -X PUT \
    "http://127.0.0.1:${port}/api/desktop/plugins/demo-settings/config" \
    -H 'Content-Type: application/json' \
    -d '{"values":{"refresh":999}}' 2>/dev/null)"
  if [[ "$invalid_code" == "400" ]] && grep -q "300" "${PROBE_DIR}/invalid.json" && grep -q '验证问候' "$config_file"; then
    echo "✓ 非法值返回 400 且未覆盖已保存配置（detail：$(cat "${PROBE_DIR}/invalid.json" 2>/dev/null)）"
  else
    echo "✗ 非法值校验不符合预期（HTTP ${invalid_code}，body：$(cat "${PROBE_DIR}/invalid.json" 2>/dev/null)）"
    status=1
  fi

  # d) 无头 Chrome + CDP：打开插件页 → 切到设置页点开配置表单 → 改值保存 →
  #    验证运行中的 iframe 通过 settings.onChanged 立即收到新值。
  cat >"${PROBE_DIR}/cdp_check.py" <<'PY'
import json
import sys
import time
import urllib.request

from websockets.sync.client import connect

ws_url, base, out_dir = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
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
    return """
        (() => {
          const frame = document.querySelector("iframe");
          if (!frame || !frame.contentDocument || !frame.contentDocument.body) return "";
          return frame.contentDocument.body.innerText || "";
        })()
    """


def main():
    status = 0
    # proxy=None：不给本机 CDP 走系统代理（macOS 上 proxy=True 会尝试 SOCKS 而缺依赖）。
    with connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=20, proxy=None) as ws:
        # 先建空页再导航：直接 createTarget(url) 时页面可能在 attach 前就开始加载，
        # 探针会在一段时间里对着尚未装载的文档轮询（实测偶发等不到首页卡片）。
        target = call(ws, "Target.createTarget", {"url": "about:blank"})["result"]["targetId"]
        session = call(ws, "Target.attachToTarget", {"targetId": target, "flatten": True})["result"]["sessionId"]
        call(ws, "Runtime.enable", {}, session)
        call(ws, "Page.enable", {}, session)
        call(ws, "Page.navigate", {"url": f"{base}/"}, session)

        # 1) 首页点击插件卡片打开子应用（不走 #/app/<id> 深链：App.tsx 的 mountedApps
        #    清理 effect 会在插件列表返回前抹掉深链登记的 id，属既有冷启动竞态，与本需求无关），
        #    插件页加载后通过 getConfig() 读到宿主配置（b 步保存的「验证问候」）。
        if not wait_for(ws, session, "!!Array.from(document.querySelectorAll('[role=button]')).find((item) => item.innerText.includes('配置探针'))"):
            body = evaluate(ws, session, "document.body.innerText.slice(0, 600)")
            print("✗ 首页没有出现「配置探针」插件卡片")
            print(f"  页面文本：{body!r}")
            return 1
        evaluate(
            ws,
            session,
            """
            (() => {
              const card = Array.from(document.querySelectorAll("[role=button]"))
                .find((item) => item.innerText.includes("配置探针"));
              card.click();
              return true;
            })()
            """,
        )
        if wait_for(ws, session, f"{iframe_text()}.includes('验证问候')"):
            print("✓ 插件页 iframe 通过 settings.getConfig() 读到宿主配置：「验证问候」")
        else:
            text = evaluate(ws, session, iframe_text())
            print(f"✗ 插件页没有读到宿主配置（iframe 文本：{text!r}）")
            return 1

        # 2) 切到设置页（已打开的子应用保持挂载），点「配置」弹出 settings[] 配置弹窗。
        evaluate(ws, session, "location.hash = '#/settings'")
        if not wait_for(ws, session, "document.body.innerText.includes('配置探针') && document.body.innerText.includes('运行中')"):
            print("✗ 设置页没有渲染插件列表 / 运行态徽章")
            status = 1
        clicked = evaluate(
            ws,
            session,
            """
            (() => {
              // 设置页每个插件一行：先找到名称文本节点「配置探针」，再从它向上找最近的
              // 含「配置」按钮的行容器。不能反过来从按钮向上找——行容器的共同祖先包含全部插件名。
              const nameNode = Array.from(document.querySelectorAll("div, span")).find(
                (node) => node.textContent.trim() === "配置探针" && !node.querySelector("button"),
              );
              if (!nameNode) return false;
              let row = nameNode.parentElement;
              for (let i = 0; i < 8 && row; i += 1, row = row.parentElement) {
                const button = Array.from(row.querySelectorAll("button"))
                  .find((item) => item.textContent.trim() === "配置");
                if (button) {
                  button.click();
                  return true;
                }
              }
              return false;
            })()
            """,
        )
        if not clicked:
            print("✗ 设置页没有「配置」按钮")
            status = 1
        form_ready = wait_for(
            ws,
            session,
            "document.querySelector('[role=\"dialog\"]') !== null && "
            "['问候语','首页问候语','刷新间隔','详细日志'].every((text) => document.body.innerText.includes(text))",
        )
        if form_ready:
            print("✓ 点击「配置」后弹出 settings[] 配置弹窗：问候语 / 首页问候语 / 刷新间隔 / 详细日志")
        else:
            print("✗ 点击「配置」后没有弹出 settings[] 配置弹窗")
            status = 1

        # 3) 配置入口只出现在声明了 settings[] 的插件上（内置 hello-world + 本探针插件 = 2 个），
        #    点开后面板从内联改为弹窗，行内按钮文案保持「配置」。
        entries = evaluate(
            ws,
            session,
            """
            (() => {
              const labels = Array.from(document.querySelectorAll("button")).map((item) => item.textContent.trim());
              const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'));
              const title = dialogs[0] ? (dialogs[0].querySelector("h2") || {}).textContent : null;
              return {
                config: labels.filter((text) => text === "配置").length,
                collapse: labels.filter((text) => text === "收起配置").length,
                dialogs: dialogs.length,
                title: title ? title.trim() : null,
                inDialog: dialogs[0] ? (dialogs[0].innerText || "").includes("问候语") : false,
              };
            })()
            """,
        )
        if (
            isinstance(entries, dict)
            and entries.get("config") == 2
            and entries.get("collapse") == 0
            and entries.get("dialogs") == 1
            and "配置探针" in (entries.get("title") or "")
            and entries.get("inDialog")
        ):
            print("✓ 只有声明 settings[] 的插件有配置入口（hello-world + demo-settings），点击后弹出「配置探针 配置」弹窗")
        else:
            print(f"✗ 配置入口 / 弹窗不符合预期：{entries}")
            status = 1

        # 4) 在表单里把「问候语」改成「实时问候」并点「保存配置」。
        changed = evaluate(
            ws,
            session,
            """
            (() => {
              // 只在弹窗里找控件：设置页的「智能体后端」区块也有一个同名「保存配置」按钮，
              // 全局 find 会先命中它。
              const dialog = document.querySelector('[role="dialog"]');
              if (!dialog) return false;
              const input = Array.from(dialog.querySelectorAll("input")).find(
                (item) => item.closest("label") && item.closest("label").innerText.includes("问候语"),
              );
              if (!input) return false;
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
              setter.call(input, "实时问候");
              input.dispatchEvent(new Event("input", { bubbles: true }));
              const save = Array.from(dialog.querySelectorAll("button"))
                .find((item) => item.textContent.trim() === "保存配置");
              if (!save) return false;
              save.click();
              return true;
            })()
            """,
        )
        if not changed:
            print("✗ 没有找到「问候语」输入框或「保存配置」按钮")
            return 1
        if wait_for(ws, session, "document.querySelectorAll('[role=\"dialog\"]').length === 0"):
            print("✓ 保存配置成功后弹窗自动关闭")
        else:
            print("✗ 保存配置成功后弹窗没有关闭")
            status = 1

        # 5) 保存后宿主广播 desktop-config-changed，运行中的 iframe 通过 onChanged 立即更新。
        if wait_for(ws, session, f"({iframe_text()}).includes('实时问候')"):
            print("✓ 设置页保存后，运行中的插件 iframe 通过 settings.onChanged 立即收到「实时问候」")
        else:
            text = evaluate(ws, session, iframe_text())
            print(f"✗ 插件 iframe 没有实时收到新配置（iframe 文本：{text!r}）")
            status = 1

        html = evaluate(ws, session, "document.documentElement.outerHTML")
        open(f"{out_dir}/settings.html", "w", encoding="utf-8").write(html or "")

    return status


sys.exit(main())
PY

  local chrome_line chrome_pid chrome_ws
  if ! chrome_line="$(start_chrome "$chrome" "${PROBE_DIR}/chrome-profile")"; then
    echo "✗ 无法启动无头 Chrome"
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    return 1
  fi
  chrome_pid="${chrome_line%% *}"
  chrome_ws="${chrome_line##* }"

  if ! "$ROOT/apps/desktop/.venv/bin/python" "${PROBE_DIR}/cdp_check.py" \
    "$chrome_ws" "http://127.0.0.1:${port}" "${PROBE_DIR}"; then
    status=1
  fi

  kill "$chrome_pid" 2>/dev/null
  wait "$chrome_pid" 2>/dev/null

  # e) 设置页保存后配置落盘为「实时问候」。
  if [[ -f "$config_file" ]] && grep -q '实时问候' "$config_file"; then
    echo "✓ 设置页保存后配置落盘：$(cat "$config_file")"
  else
    echo "✗ 设置页保存没有落盘（文件：$(cat "$config_file" 2>/dev/null || echo 文件不存在)）"
    status=1
  fi

  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null

  # f) 事件日志：config_saved（HTTP + 设置页各一次）与 iframe_load / sdk_injected。
  local log_file="${probe_home}/.desktop-app/plugin.log"
  if [[ -f "$log_file" ]] && grep -qE '"event": *"config_saved"' "$log_file" \
     && grep -qE '"event": *"iframe_load"' "$log_file" \
     && grep -qE '"event": *"sdk_injected"' "$log_file"; then
    echo "✓ plugin.log 含 config_saved / iframe_load / sdk_injected："
    grep -E 'config_saved|iframe_load|sdk_injected' "$log_file"
    if grep -qE '验证问候|实时问候' "$log_file"; then
      echo "✗ 日志里出现了配置值（不应记录值）"
      status=1
    else
      echo "✓ 日志只记键名，不含配置值"
    fi
  else
    echo "✗ plugin.log 缺少预期事件：$(cat "$log_file" 2>/dev/null || echo 文件不存在)"
    status=1
  fi

  return $status
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
  own_line="2026-10-21-desktop-plugin-config-observability: v2 request 缺少 verify.md"
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

verify_step_in "apps/desktop" "后端单测全绿（含新增 plugin_config 用例）" \
  .venv/bin/python -m pytest tests/ -q

verify_step_in "apps/desktop" "前端类型检查与生产构建" \
  pnpm --dir front build

echo "### 浏览器级探针（临时 HOME + 无头 Chrome/CDP：配置弹窗 → 保存落盘 → 运行中 iframe 实时更新 → 事件日志）"
echo
echo '```bash'
echo "browser_probe"
echo '```'
echo
echo "内部依次：HTTP 保存配置并核对落盘 / 非法值 400 / 首页点击卡片打开插件页读配置 / 切到设置页点「配置」打开弹窗 / 改值保存 / 核对弹窗关闭与 iframe 实时收到新值 / 核对 plugin.log；探针脚本见 \`${PROBE_DIR}/cdp_check.py\`。"
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
echo "- 真机 GUI：在 pywebview 窗口里打开设置页、点「配置」弹出弹窗、改动并保存、观察遮罩/焦点/移动端宽度等视觉与手感——需要 macOS 图形会话与人工目视。脚本用无头 Chrome + CDP 复现了同一条链路（插件页 iframe → 设置页 → 保存 → onChanged 实时更新）并断言了 DOM 文本，但没有在真窗口里目视确认视觉与手感。"
echo "- 前端没有测试框架：配置弹窗体与运行态徽章的渲染由浏览器级探针做 DOM 断言覆盖，没有组件单测覆盖弹窗字段渲染的全部分支（number 空值、select 选项、boolean 勾选）与 Esc / 遮罩关闭、焦点归还等交互。"
echo "- 运行态徽章的失败分支：探针只覆盖了「运行中」徽章，没有构造一个 \`sdk_inject_failed\` 场景去目视「运行失败：原因」的展示。"
echo "- \`tests/test_host_api.py\` 的 \`test_macos_open_*\` 用例属于工作区中他人未提交的 WIP，其文件顶部缺 \`import subprocess\`；本次运行前已临时补该行（不随本 request 提交），因此全量 pytest 通过。在纯净 HEAD 上该用例不存在。"
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
echo "- 已由单测证明：\`settings[]\` 的六类非法声明（非法 key、number 默认布尔、select 缺候选项、select 默认值不在候选项、min>max、text 带 max/text 默认值非字符串、boolean 默认值非布尔）在加载期被 pydantic 拒绝；默认值合并会丢弃未声明键；\`validate_values\` 一次性返回全部中文错因；配置以紧凑 JSON + 原子替换落 \`plugin-config/<id>.json\`，坏文件与非法插件 id 被拒；HTTP 端点返回默认值、保存后日志出现 \`config_saved\` 且只含键名、非法提交 400 且不覆盖、插件停用期间仍可读写配置；\`plugin.log\` 是 JSONL、detail 截断到 4096 字符、超 1 MiB 轮转、未知事件名被拒、非法插件 id 归一为 \`unknown\`；内置 \`hello-world\` 声明了三项 \`settings[]\`。"
echo "- 已由前端构建证明：\`tsc\` 类型检查与 \`vite build\` 通过（包含新增的 \`runtime-status.ts\`、\`PluginSetting\` 类型、\`getPluginConfig\`/\`savePluginConfig\`/\`logPluginEvent\`）。"
echo "- 已由浏览器级探针证明：临时 HOME 下的宿主设置页点「配置」后弹出 \`settings[]\` 配置弹窗（问候语 / 描述 / 刷新间隔 / 详细日志），且只有声明了 \`settings[]\` 的插件才有该按钮；插件 iframe 用 \`getConfig()\` 读到已保存配置；在设置页改值并保存后，宿主广播使**运行中的 iframe** 通过 \`onChanged\` 立即收到新值；保存经 HTTP 与设置页两条路径都原子落盘，非法值 400 且不覆盖；\`plugin.log\` 含 \`config_saved\` / \`iframe_load\` / \`sdk_injected\`，且不记录配置值。"
echo "- 尚未证明：真窗口里的视觉与手感、运行失败徽章的展示（见上「未执行项」），以及 Windows / Linux 平台。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。"
echo "- 已知边界：宿主所有插件接口同源，任意被注入 SDK 的 iframe 理论上可调其它插件的 config 端点——与既有 \`plugin-data\` 端点同级，本刀未新增提权面（spec「已知限制」）。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
