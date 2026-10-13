#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-13-desktop-app-new-window
#
# 覆盖范围：插件 manifest 的 open_mode 契约、宿主桥 open_app/close_current_window、
# 子窗口管理器、前端产物是否带上三种打开方式，以及一次「真起内嵌服务 + 真跑 main.run() 装配」
# 的端到端探针（只把 pywebview 的窗口层换成替身）。
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

verify_step_in "apps/desktop" \
  "后端单元测试（open_mode 校验 / 窗口管理器 / 宿主桥 open_app）" \
  .venv/bin/python -m pytest -q

verify_step_in "apps/desktop/front" "前端类型检查" ./node_modules/.bin/tsc --noEmit

verify_step_in "apps/desktop/front" "前端构建" pnpm build

# pnpm 会往 apps/desktop/package.json 自动补 packageManager 字段；本 request 不改该文件，
# 构建后按 git 版本还原，避免验证过程污染工作区。
verify_step "还原构建顺带改动的 package.json" \
  bash -c 'cd apps/desktop && git checkout -- package.json 2>/dev/null; git diff --quiet -- package.json'

verify_step "前端产物包含三种打开方式与两个桥方法" bash -c '
  set -e
  bundle=$(ls apps/desktop/front/dist/assets/index-*.js)
  echo "产物：${bundle}"
  for text in 在当前页面打开 在系统浏览器打开 在新的原生窗口打开; do
    count=$(grep -c "$text" "$bundle" || true)
    echo "${text}: ${count}"
    [ "$count" = "1" ] || { echo "缺少文案：${text}"; exit 1; }
  done
  for symbol in open_app close_current_window; do
    count=$(grep -c "$symbol" "$bundle" || true)
    echo "${symbol}: ${count}"
    [ "$count" -ge 1 ] || { echo "缺少桥调用：${symbol}"; exit 1; }
  done
  [ "$(grep -c "child" "$bundle" || true)" -ge 1 ]
'

# ── 端到端探针：真起 uvicorn 内嵌服务、真 create_app/PluginManager/HostApi/AppWindowManager ──
cat >"${PROBE_DIR}/probe_host_wiring.py" <<'PY'
"""端到端探针：真的起内嵌服务、真的跑 main.run() 的装配，只把 pywebview 的窗口层换成替身。

pywebview 真开窗口需要图形会话，脚本里开不了；但「点击卡片按插件声明的默认方式打开、
子窗口深链回宿主壳、关主窗口清理子窗口并停服务」全是真实代码路径，探针只替换
webview.create_window / webview.start。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import webview

# 播种一个声明 open_mode="window" 的用户插件：验证「默认打开方式由插件决定」的端到端链路。
user_plugin = Path(os.environ["HOME"]) / ".desktop-app" / "plugins" / "native-app"
user_plugin.mkdir(parents=True, exist_ok=True)
(user_plugin / "manifest.json").write_text(
    json.dumps(
        {
            "id": "native-app",
            "name": "原生窗口应用",
            "version": "0.1.0",
            "entry": "index.html",
            "open_mode": "window",
            "permissions": ["storage"],
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
(user_plugin / "index.html").write_text("<!doctype html><title>native-app</title>", encoding="utf-8")

from desktop_app import host_api as host_api_module  # noqa: E402
from desktop_app import main as desktop_main  # noqa: E402

CREATED: list = []
STARTED: dict = {}


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def emit(self) -> None:
        for handler in list(self.handlers):
            handler()


class FakeWindow:
    def __init__(self, title: str, **options) -> None:
        self.title = title
        self.options = options
        self.calls: list[str] = []

        class _Events:
            def __init__(self) -> None:
                self.closed = FakeEvent()

        self.events = _Events()

    def show(self) -> None:
        self.calls.append("show")

    def restore(self) -> None:
        self.calls.append("restore")

    def destroy(self) -> None:
        self.calls.append("destroy")


def fake_create_window(title: str, **options) -> FakeWindow:
    window = FakeWindow(title, **options)
    CREATED.append(window)
    return window


def fake_start(**kwargs) -> None:
    STARTED.update(kwargs)


def http_get(url: str, timeout: float = 10.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


webview.create_window = fake_create_window
webview.start = fake_start

# ── 真实装配：真起 uvicorn 内嵌服务、真 create_app、真 HostApi + AppWindowManager ──
desktop_main.run()

assert len(CREATED) == 1, f"主窗口应恰好创建一个，实际 {len(CREATED)}"
master = CREATED[0]
base = master.options["url"]
api = master.options["js_api"]
assert base.startswith("http://127.0.0.1:"), base
print(f"主窗口：url={base}，js_api={type(api).__name__}，webview.start 参数={sorted(STARTED)}")

# ── 真 HTTP：宿主壳页面与插件列表接口 ──
shell_html = http_get(f"{base}/")
assert '<div id="root">' in shell_html, shell_html[:200]
print(f"宿主壳页面：HTTP 200 / {len(shell_html)} 字节")

items = json.loads(http_get(f"{base}/api/desktop/plugins"))["items"]
modes = {p["id"]: p["openMode"] for p in items}
print("插件默认打开方式：", modes)
assert modes.get("hello-world") == "inline", modes  # 未声明 open_mode 的老插件保持原行为
assert modes.get("native-app") == "window", modes  # 声明了 window 的插件如实暴露给前端

# ── inline：后端只回执，不建窗口 ──
inline = api.open_app("hello-world")
assert inline == {"ok": True, "mode": "inline", "target": None, "reused": False}, inline
assert len(CREATED) == 1, "inline 不应创建窗口"
print("inline：只回执，未创建窗口")

# ── 不指定 mode：按插件声明的默认方式（native-app 声明的是 window）──
default_window = api.open_app("native-app")
assert default_window["mode"] == "window" and default_window["reused"] is False, default_window
assert default_window["target"].endswith("/?child=1#/app/native-app"), default_window["target"]
assert len(CREATED) == 2
native_child = CREATED[1]
assert native_child.options["js_api"] is api, "子窗口必须复用同一个宿主桥"
assert native_child.options["url"] == default_window["target"]
# 深链去掉 hash 后能真的取回同一份壳页面（证明确实开的是宿主壳，而不是插件页）
assert http_get(default_window["target"].split("#")[0]) == shell_html
print("插件默认 window：未指定 mode 即开子窗口，且深链取回同一份壳页面")

# ── 显式覆盖：hello-world 声明 inline，但右键选 window ──
opened = api.open_app("hello-world", "window")
assert opened["ok"] is True and opened["mode"] == "window" and opened["reused"] is False, opened
assert opened["target"] == f"{base}/?child=1#/app/hello-world", opened["target"]
assert len(CREATED) == 3
child = CREATED[2]
assert child.options["js_api"] is api, "子窗口必须复用同一个宿主桥"
print("window 覆盖：显式 mode 压过 manifest 默认值")

# ── 重复打开：只聚焦已有窗口，不再新开 ──
again = api.open_app("hello-world", "window")
assert again["reused"] is True, again
assert len(CREATED) == 3, "重复打开不应新建窗口"
assert child.calls == ["restore", "show"], child.calls
print("重复打开：复用并聚焦已有窗口")

# ── 系统启动器：未知协议必须被识别为失败（真机 open 命令，无副作用） ──
if sys.platform == "darwin":
    probe_launcher = host_api_module._macos_open("dsh-probe://no-such-handler")
    assert probe_launcher is False, f"未知协议应判定失败，实际 {probe_launcher!r}"
    print("系统启动器：未知协议返回 False（不再静默谎报成功）")

# ── browser：交给系统浏览器，不建窗口（拦截启动器，避免自动验证真弹标签页） ──
browser_calls: list[str] = []
original_open = host_api_module.webbrowser.open
original_macos = host_api_module._macos_open
host_api_module._macos_open = lambda target, timeout=5.0: None
host_api_module.webbrowser.open = lambda url, new=0: browser_calls.append(url) or True
try:
    browser = api.open_app("hello-world", "browser")
finally:
    host_api_module.webbrowser.open = original_open
    host_api_module._macos_open = original_macos
# 浏览器标签页不是原生窗口：深链不带 ?child=1，Esc / 返回 应退回应用列表
assert browser["ok"] is True and browser["mode"] == "browser", browser
assert browser_calls == [f"{base}/#/app/hello-world"], browser_calls
assert len(CREATED) == 3, "browser 不应创建窗口"

# 浏览器起不来时必须如实回执失败，前端才能提示用户
host_api_module._macos_open = lambda target, timeout=5.0: False
try:
    failed = api.open_app("hello-world", "browser")
finally:
    host_api_module._macos_open = original_macos
assert failed["ok"] is False and failed["reason"] == "browser_failed", failed
print("browser：只调用系统浏览器、不建窗口、深链不带 child=1；启动失败回执 browser_failed")

# ── 未知插件与非法 mode ──
assert api.open_app("not-installed", "window")["reason"] == "not_found"
fallback = api.open_app("hello-world", "newwindow")
assert fallback["mode"] == "inline", fallback
print("未知插件：reason=not_found；非法 mode：回退 inline")

# ── 主窗口关闭：先销毁所有子窗口，再停内嵌服务（不留残窗、不留服务） ──
master.events.closed.emit()
assert child.calls == ["restore", "show", "destroy"], child.calls
assert native_child.calls == ["destroy"], native_child.calls
print("主窗口关闭：已打开的 2 个子窗口全部销毁")

deadline = time.monotonic() + 10
while True:
    try:
        http_get(f"{base}/api/desktop/plugins", timeout=1)
    except Exception:
        break
    if time.monotonic() > deadline:
        raise AssertionError("主窗口关闭后内嵌服务仍在提供响应")
    time.sleep(0.1)
print("内嵌服务：已停止（HTTP 不再响应）")
print("端到端探针结论：通过")
PY

# HOME 指到探针目录：插件管理器只看得到内置插件 + 探针播种的 native-app，结果可复现。
mkdir -p "${PROBE_DIR}/home"
verify_step "端到端装配探针（真起内嵌服务 + 真跑 main.run()，仅替换 pywebview 窗口层）" \
  env HOME="${PROBE_DIR}/home" PYTHONPATH=apps/desktop \
  apps/desktop/.venv/bin/python "${PROBE_DIR}/probe_host_wiring.py"

echo "## 未执行项与原因"
echo
echo "- 真机 GUI 行为：真实弹出原生子窗口、在卡片上右键出菜单、子窗口内按 Esc 关窗、关主窗口后系统里无残留窗口——需要 macOS 图形会话与人工目视，脚本内无法断言（探针只替换了 pywebview 的窗口层，没有真正渲染）。"
echo "- 真实弹出浏览器标签页：脚本会拦截系统启动器（\`_macos_open\`）以免自动验证时弹出窗口，只用真机 \`open\` 命令验证「未知协议返回失败」这一路径；「点击后浏览器里真的出现壳页面」需人工目视。"
echo "- macOS 上 \`webview.active_window()\` 的真实返回值与对话框归属：pywebview 依赖 AppKit 的 keyWindow，只在真机上才有意义，本次仅由单元测试用 monkeypatch 覆盖。"
echo "- 浏览器（无 pywebview 桥）里的降级表现：需要在浏览器中打开壳页面，点击卡片确认弹出「浏览器调试模式不支持该打开方式」并回退为壳内打开——需人工目视。"
echo "- Windows / Linux 平台：本机只有 macOS 环境，未在其它平台执行。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
echo "- 已由脚本证明：插件未声明 \`open_mode\` 时默认 inline（hello-world 端到端仍走原路径）；声明 \`window\` 的插件未指定 mode 即开子窗口；显式 mode 可覆盖 manifest 默认值；子窗口目标是带 \`?child=1\` 的壳深链且复用同一个宿主桥（remote 插件不挂桥由单元测试覆盖）；重复打开只聚焦不新开；browser 模式只调系统浏览器、目标是不带 \`?child=1\` 的深链、启动失败回执 \`browser_failed\`（macOS 用 \`/usr/bin/open\` 并检查退出码，未知协议判定失败）；未知插件返回 \`not_found\`、非法 mode 回退 inline；主窗口关闭时子窗口全部销毁且内嵌服务停止；前端类型检查与构建通过，产物带上三种打开方式文案与 \`open_app\`/\`close_current_window\` 调用。"
echo "- 尚未证明：真实窗口的视觉与交互（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已通过人工联调。"
echo "- 剩余风险：子窗口与主窗口共用同一个 \`HostApi\` 实例，插件在子窗口里的 \`navigate()\` 只改本窗口 hash（预期行为）；跨窗口状态同步不在本 request 范围内。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
