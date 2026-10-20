---
source: script
request: 2026-10-20-ledger-app
ranAt: "2026-10-20 22:56:32 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端全量测试（排除仓库既有失败的 test_host_api 用例）

```bash
cd apps/desktop && .venv/bin/python -m pytest -q --deselect tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off
```

........................................................................ [ 32%]
........................................................................ [ 64%]
........................................................................ [ 96%]
........                                                                 [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
224 passed, 1 deselected, 1 warning in 1.74s
结果：通过

### Ruff 检查本 request 相关 Python 文件

```bash
cd apps/desktop && .venv/bin/python -m ruff check desktop_app tests/test_plugin_data.py tests/test_dev_agent.py tests/test_agent_config.py
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
✓ 22 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.39 kB │ gzip:  0.27 kB
dist/assets/index-BIEfS8vg.css    6.20 kB │ gzip:  1.88 kB
dist/assets/index-Bt28EJFo.js   239.54 kB │ gzip: 75.52 kB

✓ built in 118ms
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

### 宿主工具策略创建提交事务的回归测试（create_policy commit/refresh）

```bash
cd apps/backend && .venv/bin/python -m pytest tests/host_tool/ -q
```

.............                                                            [100%]
13 passed in 3.15s
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
dist/assets/index-B6L_QMDj.css   63.99 kB │ gzip:  12.53 kB
dist/assets/index-MugmuFQ5.js   591.22 kB │ gzip: 196.30 kB

✓ built in 297ms
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
  target='/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.loRbDMDltQ/plugins'
  node apps/ledger/scripts/install-to-desktop.mjs --target "$target" --json > '/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.loRbDMDltQ/install.json'
  cat '/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.loRbDMDltQ/install.json'
  test -f "$target/index.html"
  test -f "$target/manifest.json"
  ls "$target"/assets/*.js >/dev/null

```

{"installedTo":"/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.loRbDMDltQ/plugins","zip":null}
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
env PYTHONPATH=apps/desktop apps/desktop/.venv/bin/python /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.loRbDMDltQ/probe_e2e.py /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.loRbDMDltQ/e2e
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

### 真实模型链路（AI Base 签发 token + 模型自发调用 ledger_add_entry）

```bash
real_model_probe
```

token OK，endpoint: ws://127.0.0.1:8000/api/v1/ws/agents/1 platformId: 1
真实模型调用: ['ledger_add_entry']
最终回复: 已记录： /  / - 日期：2026-10-20 / - 类型：支出 / - 金额：35.00 元 / - 分类：餐饮 / - 备注：午饭 /  / 2026 年 10 月汇总：支出 35.00 元，收入 0.00 元，结余 -35.00 元。
结果：通过

### 宿主首页启动即预挂载 tools 子应用（无头 Chrome + 本地 dev 网关，验证 5 个方法注册到助手）

```bash
premount_probe
```

{"installedTo":"/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.loRbDMDltQ/premount-home/.desktop-app/plugins/ledger","zip":null}
结果：通过

## 未执行项与原因

- 真机 GUI：在 pywebview 窗口里打开「记账」卡片、点击记一笔、看月汇总、重启应用后数据仍在——需要 macOS 图形会话与人工目视，脚本用 TestClient 验证了同一条服务链路（静态托管 + plugin-data + WS），但没有真正渲染界面。
- 浏览器里 ai-sdk 悬浮窗的视觉与交互（悬浮球、展开面板、消息气泡、工具结果卡片）：脚本用无头 Chrome 只取了 DOM 与后端注册日志，没有截图或点击断言，视觉需要打开宿主应用目视。
- 真机 pywebview 窗口内的 iframe 常驻与「不打开应用也能用方法」的最终体感：脚本用无头 Chrome 复现了同一条链路（首页渲染 → 隐藏 iframe 加载 → `desktop.tools.register` → dev 网关收到 5 个方法注册），但没有在 pywebview 窗口里目视确认悬浮球位置与记账页交互。
- `tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off`：仓库内他人未提交改动导致 `NameError: name 'subprocess' is not defined`（`tests/test_host_api.py:210`），与本 request 无关，已从 pytest 中 deselect，未修复该文件。
- `apps/ledger` 的浏览器层（localStorage 降级、向宿主迁移、界面交互）没有自动化测试：子应用本身不引入测试框架，相关行为在本轮实现时用临时断言脚本验证过，未固化为仓库内测试。
- 设置页「智能体后端」表单的交互（保存/测试连接/清除）没有前端测试：宿主前端无测试框架，本次用 `tsc --noEmit` 与真实 HTTP 路由测试覆盖，未做浏览器点击验证。
- Windows / Linux：本机只有 macOS 环境，未在其它平台执行。

## 验收结论

- 已由脚本证明：`apps/ledger` 能独立构建出合法 iframe 插件（manifest id/type/entry/permissions 正确，产物内含 5 个方法名）；宿主前端 `tsc --noEmit` 与生产构建通过；安装脚本能把 dist 同步到目标插件目录；宿主 plugin-data 接口能按插件隔离地写入/读取 JSON，且需要插件声明 `storage` 权限；`GET /api/desktop/agent-config` 在 `dev_agent_enabled=True` 时返回本地网关参数；真实 WS 会话能完成 `session_ready` → `host_tools_register` → `message_send` → `host_tool_call(ledger_add_entry, amount=35)` → `host_tool_result` → `message_completed`（含 35.00）的完整回环（TestClient 内存传输与真实 uvicorn + websockets 进程各验证一次）；5 个方法名在子应用实现、子应用 README、宿主 README 三处一致。
- 已由浏览器级回归证明：宿主首页在**没有打开任何子应用**的情况下，无头 Chrome 渲染后 dev 网关收到了 `ledger_add_entry` 等 5 个方法的注册帧——即「声明 tools 权限的子应用启动即静默挂载」这条修复生效。
- 尚未证明：真实窗口里的界面交互与视觉、悬浮球/面板的观感（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已通过人工联调。
- 真实模型：宿主保存的 Embed Client 凭证（或仓库根 .env 的 `EMBED_*`）能换到 token，模型在「请调用 ledger_add_entry 记一笔」时确实调用了 `ledger_add_entry` 并接受工具返回结果；后台 5 条策略与 Agent/Client 绑定由 `apps/desktop/scripts/configure_ai_base.py` 一次性写入（本脚本不做写入，避免污染后台数据）。
- 剩余风险：真实模型对工具的选择受提示与模型版本影响，脚本只验证「会调用正确方法」这一条主路径，没有覆盖模型绕开工具、先查后记等分支；desktop 的 dev agent 仍是规则式 mock，只用于无网络闭环。
