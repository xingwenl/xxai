---
source: script
request: 2026-10-13-desktop-app-new-window
ranAt: "2026-10-13 18:56:51 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端单元测试（open_mode 校验 / 窗口管理器 / 宿主桥 open_app）

```bash
cd apps/desktop && .venv/bin/python -m pytest -q
```

........................................................................ [ 48%]
........................................................................ [ 97%]
....                                                                     [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
148 passed, 1 warning in 1.94s
结果：通过

### 前端类型检查

```bash
cd apps/desktop/front && ./node_modules/.bin/tsc --noEmit
```

结果：通过

### 前端构建

```bash
cd apps/desktop/front && pnpm build
```

! The local project doesn't define a 'packageManager' field. Corepack will now add one referencing pnpm@9.15.9+sha512.68046141893c66fad01c079231128e9afb89ef87e2691d69e4d40eee228988295fd4682181bae55b58418c3a253bde65a505ec7c5f9403ece5cc3cd37dcf2531.
! For more details about this field, consult the documentation at https://nodejs.org/api/packages.html#packagemanager


> desktop-front@0.2.0 build /Users/lixingwen/xw/study/ai-base/apps/desktop/front
> vite build

vite v8.0.3 building client environment for production...
[2Ktransforming...✓ 26 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.39 kB │ gzip:  0.26 kB
dist/assets/index-BKNmsKCz.css   19.85 kB │ gzip:  4.89 kB
dist/assets/index-0B3yP1g1.js   255.76 kB │ gzip: 76.07 kB

✓ built in 339ms
结果：通过

### 还原构建顺带改动的 package.json

```bash
bash -c cd apps/desktop && git checkout -- package.json 2>/dev/null; git diff --quiet -- package.json
```

结果：通过

### 前端产物包含三种打开方式与两个桥方法

```bash
bash -c 
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

```

产物：apps/desktop/front/dist/assets/index-0B3yP1g1.js
在当前页面打开: 1
在系统浏览器打开: 1
在新的原生窗口打开: 1
open_app: 1
close_current_window: 1
结果：通过

### 端到端装配探针（真起内嵌服务 + 真跑 main.run()，仅替换 pywebview 窗口层）

```bash
env HOME=/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Id81ZLzmXE/home PYTHONPATH=apps/desktop apps/desktop/.venv/bin/python /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Id81ZLzmXE/probe_host_wiring.py
```

主窗口：url=http://127.0.0.1:61310，js_api=HostApi，webview.start 参数=['debug', 'icon', 'private_mode']
宿主壳页面：HTTP 200 / 390 字节
插件默认打开方式： {'bookmarks-organizer': 'inline', 'hello-world': 'inline', 'native-app': 'window'}
inline：只回执，未创建窗口
插件默认 window：未指定 mode 即开子窗口，且深链取回同一份壳页面
window 覆盖：显式 mode 压过 manifest 默认值
重复打开：复用并聚焦已有窗口
browser：只调用系统浏览器，未创建窗口
未知插件：reason=not_found；非法 mode：回退 inline
主窗口关闭：已打开的 2 个子窗口全部销毁
内嵌服务：已停止（HTTP 不再响应）
端到端探针结论：通过
结果：通过

## 未执行项与原因

- 真机 GUI 行为：真实弹出原生子窗口、在卡片上右键出菜单、子窗口内按 Esc 关窗、关主窗口后系统里无残留窗口——需要 macOS 图形会话与人工目视，脚本内无法断言（探针只替换了 pywebview 的窗口层，没有真正渲染）。
- macOS 上 `webview.active_window()` 的真实返回值与对话框归属：pywebview 依赖 AppKit 的 keyWindow，只在真机上才有意义，本次仅由单元测试用 monkeypatch 覆盖。
- 浏览器（无 pywebview 桥）里的降级表现：需要在浏览器中打开壳页面，点击卡片确认弹出「浏览器调试模式不支持该打开方式」并回退为壳内打开——需人工目视。
- Windows / Linux 平台：本机只有 macOS 环境，未在其它平台执行。

## 验收结论

- 已由脚本证明：插件未声明 `open_mode` 时默认 inline（hello-world 端到端仍走原路径）；声明 `window` 的插件未指定 mode 即开子窗口；显式 mode 可覆盖 manifest 默认值；子窗口目标是带 `?child=1` 的壳深链且复用同一个宿主桥（remote 插件不挂桥由单元测试覆盖）；重复打开只聚焦不新开；browser 模式只调系统浏览器；未知插件返回 `not_found`、非法 mode 回退 inline；主窗口关闭时子窗口全部销毁且内嵌服务停止；前端类型检查与构建通过，产物带上三种打开方式文案与 `open_app`/`close_current_window` 调用。
- 尚未证明：真实窗口的视觉与交互（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已通过人工联调。
- 剩余风险：子窗口与主窗口共用同一个 `HostApi` 实例，插件在子窗口里的 `navigate()` 只改本窗口 hash（预期行为）；跨窗口状态同步不在本 request 范围内。
