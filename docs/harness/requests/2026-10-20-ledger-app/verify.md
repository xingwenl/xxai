---
source: script
request: 2026-10-20-ledger-app
ranAt: "2026-10-20 18:44:28 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端全量测试（排除仓库既有失败的 test_host_api 用例）

```bash
cd apps/desktop && .venv/bin/python -m pytest -q --deselect tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off
```

........................................................................ [ 38%]
........................................................................ [ 76%]
.............................................                            [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
189 passed, 1 deselected, 1 warning in 1.06s
结果：通过

### Ruff 检查本 request 相关 Python 文件

```bash
cd apps/desktop && .venv/bin/python -m ruff check desktop_app tests/test_plugin_data.py tests/test_dev_agent.py
```

All checks passed!
结果：通过

### 子应用构建（tsc --noEmit + vite build）

```bash
cd apps/ledger && pnpm build
```


> ledger-web@0.1.0 build /Users/lixingwen/xw/study/ai-base/apps/ledger
> tsc --noEmit && vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 21 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.39 kB │ gzip:  0.28 kB
dist/assets/index-BIEfS8vg.css    6.20 kB │ gzip:  1.88 kB
dist/assets/index-ZZlXDEM4.js   239.51 kB │ gzip: 75.49 kB

✓ built in 86ms
结果：通过

### 子应用产物是合法 iframe 插件且带上 5 个方法名

```bash
bash -c 
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

```

产物校验：通过
结果：通过

### 宿主前端类型检查

```bash
cd apps/desktop/front && ./node_modules/.bin/tsc --noEmit
```

结果：通过

### 宿主前端构建

```bash
pnpm --dir apps/desktop/front build
```


> desktop-front@0.2.0 build /Users/lixingwen/xw/study/ai-base/apps/desktop/front
> vite build

(!) Your Vite config uses features that are unsupported by `configLoader: 'native'`, which is planned to become the default in a future major version of Vite:
  - `__dirname` (vite.config.ts:13:27). Use `import.meta.dirname` instead
Set `VITE_CONFIG_NATIVE_IGNORE_WARNING=true` to suppress this warning.
vite v8.3.4 building client environment for production...
transforming...
✓ 31 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.39 kB │ gzip:   0.26 kB
dist/assets/index-Cbe8oeQg.css   63.88 kB │ gzip:  12.51 kB
dist/assets/index-CId-fEur.js   584.43 kB │ gzip: 194.73 kB

✓ built in 187ms
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### 安装脚本把 dist 同步到指定插件目录

```bash
bash -c 
  set -e
  target='/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.S9Ber7VFgE/plugins'
  node apps/ledger/scripts/install-to-desktop.mjs --target "$target" --json > '/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.S9Ber7VFgE/install.json'
  cat '/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.S9Ber7VFgE/install.json'
  test -f "$target/index.html"
  test -f "$target/manifest.json"
  ls "$target"/assets/*.js >/dev/null

```

{"installedTo":"/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.S9Ber7VFgE/plugins","zip":null}
结果：通过

### README 与实现三方方法契约一致

```bash
bash -c 
  set -e
  for f in apps/ledger/src/lib/tools.ts apps/ledger/README.md apps/desktop/README.md; do
    for name in ledger_add_entry ledger_list_entries ledger_month_summary ledger_delete_entry ledger_list_categories; do
      grep -q "$name" "$f" || { echo "缺少 $name：$f"; exit 1; }
    done
  done
  echo "契约一致性：通过"

```

契约一致性：通过
结果：通过

### 端到端探针（插件托管 + plugin-data + dev agent WS 工具回环）

```bash
env PYTHONPATH=apps/desktop apps/desktop/.venv/bin/python /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.S9Ber7VFgE/probe_e2e.py /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.S9Ber7VFgE/e2e
```

/Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa
回复： "已记账： 餐饮 ¥35.00（支出）。\n本月支出 ¥35.00，收入 ¥0.00，结余 ¥-35.00。"
端到端探针结论：通过
结果：通过

### 真实 uvicorn + websockets 客户端（DESKTOP_DEV_AGENT=1 的 WS 网关）

```bash
real_ws_probe
```

回复： 已记账： 餐饮 ¥35.00（支出）。 / 本月支出 ¥35.00，收入 ¥0.00，结余 ¥-35.00。
真实 WS 结论：通过
结果：通过

## 未执行项与原因

- 真机 GUI：在 pywebview 窗口里打开「记账」卡片、点击记一笔、看月汇总、重启应用后数据仍在——需要 macOS 图形会话与人工目视，脚本用 TestClient 验证了同一条服务链路（静态托管 + plugin-data + WS），但没有真正渲染界面。
- 浏览器里 ai-sdk 悬浮窗 ↔ 子应用方法注册这一跳：脚本用 TestClient 与真实 uvicorn + websockets 客户端模拟 ai-agent.v1 协议完成握手与工具回环，但没有启动 pywebview + 浏览器渲染 ai-sdk 悬浮窗，也没有验证 iframe 内 `desktop.tools.register` 经 tool-bridge 同步给助手的实际效果，需要打开宿主应用目视。
- `tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off`：仓库内他人未提交改动导致 `NameError: name 'subprocess' is not defined`（`tests/test_host_api.py:210`），与本 request 无关，已从 pytest 中 deselect，未修复该文件。
- `apps/ledger` 的浏览器层（localStorage 降级、向宿主迁移、界面交互）没有自动化测试：子应用本身不引入测试框架，相关行为在本轮实现时用临时断言脚本验证过，未固化为仓库内测试。
- Windows / Linux：本机只有 macOS 环境，未在其它平台执行。

## 验收结论

- 已由脚本证明：`apps/ledger` 能独立构建出合法 iframe 插件（manifest id/type/entry/permissions 正确，产物内含 5 个方法名）；宿主前端 `tsc --noEmit` 与生产构建通过；安装脚本能把 dist 同步到目标插件目录；宿主 plugin-data 接口能按插件隔离地写入/读取 JSON，且需要插件声明 `storage` 权限；`GET /api/desktop/agent-config` 在 `dev_agent_enabled=True` 时返回本地网关参数；真实 WS 会话能完成 `session_ready` → `host_tools_register` → `message_send` → `host_tool_call(ledger_add_entry, amount=35)` → `host_tool_result` → `message_completed`（含 35.00）的完整回环（TestClient 内存传输与真实 uvicorn + websockets 进程各验证一次）；5 个方法名在子应用实现、子应用 README、宿主 README 三处一致。
- 尚未证明：真实窗口里的界面交互与视觉、浏览器中 ai-sdk 悬浮窗到子应用工具注册的最后一跳（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已通过人工联调。
- 剩余风险：dev agent 是规则式 mock（关键词 + 金额正则），只用于本地闭环，不能代表真实模型对工具的选择；真实接入需 AI Base 后端签发 token 并把 `ledger_*` 绑定到 Agent 与 Embed Client、schema 指纹保持一致，这一步本 request 明确不在范围内。
