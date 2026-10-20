# 桌面子应用契约速查

本文件是 `SKILL.md` 的展开参考资料：只在真正写代码 / 写配置 / 排查时读。

## 1. 插件 manifest（`apps/<name>/public/manifest.json`）

```json
{
  "id": "ledger",
  "name": "记账",
  "version": "0.1.0",
  "description": "记账子应用：本地记账、月汇总，并向桌面助手提供 ledger_* 方法",
  "icon": "icon.svg",
  "entry": "index.html",
  "type": "iframe",
  "permissions": ["storage", "tools", "notify"]
}
```

- `id` 必须与安装目录名一致，匹配 `^[a-z0-9][a-z0-9_-]*$`。
- `type` 取 `iframe | react | remote`；第三方/独立仓库的子应用用 `iframe`。
- `entry` / `icon` 是包内相对 POSIX 路径，禁止绝对路径与 `..`。
- 宿主已知权限：`notify`、`settings`、`storage`、`events`、`http`、`platform`、`log`、`tools`。未声明的能力在 SDK 上是抛错 Proxy（`权限不足：manifest.permissions 未声明 <ability>`）。
- 宿主只托管文件，不做 SPA 深链回退：`entry` 指向的 HTML 必须真实存在；内部路由用 hash。

## 2. 方法契约（`apps/<name>/tools.json`）

```json
[
  {
    "name": "ledger_add_entry",
    "description": "记一笔账。amount 单位为元；type 取 expense(支出) 或 income(收入)；category 不传则按备注自动推断。",
    "sideEffect": "financial",
    "inputSchema": {
      "type": "object",
      "properties": {
        "amount": { "type": "number", "description": "金额，单位元，必须大于 0" },
        "type": { "type": "string", "enum": ["expense", "income"] },
        "category": { "type": "string" },
        "note": { "type": "string" }
      },
      "required": ["amount"]
    }
  }
]
```

约束（来自后端与 ai-sdk）：

| 项 | 约束 |
| --- | --- |
| 名称 | `^[A-Za-z][A-Za-z0-9_.-]{0,127}$`，建议 `<app>_<verb>_<noun>` 全下划线 |
| inputSchema | 必须 `type: "object"`，紧凑 JSON ≤64KiB；只支持 string/number/boolean/enum 等基础子集 |
| 描述 | 中文、写清单位与默认值，模型靠它决定是否调用 |
| 结果 | `JSON.stringify` 后 ≤32KiB，超限以 `host_tool_execution_failed` + message `host_tool_result_too_large` 回给模型 |
| 超时 | 默认 10s（`ToolDefinition.timeoutMs` 可覆盖），宿主侧长任务要拆步 |
| sideEffect | `none / navigation / write / financial / external`；动钱用 `financial`，会被确认策略拦截 |
| 指纹 | 后端按 `json.dumps(sort_keys=True, separators=(",",":"))` 的 sha256 比对；**同一份 schema 只能有一个来源** |

失败码：`host_tool_not_registered`（没注册）、`host_tool_arguments_invalid`（schema 校验失败）、`host_tool_execution_failed`（handler 抛错，结果超 32KiB 时 message 为 `host_tool_result_too_large`）。

## 3. 子应用侧注册骨架

```ts
import toolsSchema from '../../tools.json'

const TOOL_DEFS = toolsSchema as DesktopToolDef[]
let registered = false

const HANDLERS: Record<string, (args: unknown) => unknown | Promise<unknown>> = {
  ledger_add_entry: (args) => addEntry(args as AddEntryArgs),
}

function installTools(): void {
  const tools = window.desktop?.tools
  if (registered || !tools) return // 宿主未声明 tools 权限时静默跳过
  registered = true
  void tools.register(TOOL_DEFS, HANDLERS)
}

if (window.desktop) installTools()
window.addEventListener('desktop-ready', installTools)
```

要点：

- `desktop-ready` 由宿主在 iframe `load` 后派发，也可以在 `window.desktop` 已存在时直接注册。
- handler 入参是 `unknown`：自己校验类型再算，抛出的错误会被宿主包装成 `${pluginName}执行 ${name} 失败：...` 回给模型。
- 只有一个注册入口，重复注册同名方法会被宿主忽略并告警。

## 4. 数据持久化（宿主 plugin-data）

子应用侧：

```ts
await window.desktop.storage.set('ledger', data)          // 写
const data = await window.desktop.storage.get('ledger', null) // 读，缺失返回 fallback
await window.desktop.storage.delete('ledger')
const { keys } = { keys: await window.desktop.storage.keys!() }
```

REST（宿主 `/api/desktop/plugin-data/...`，仅宿主内部与调试用，页面走 SDK）：

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/desktop/plugin-data/{plugin_id}` | 列出 key：`{"keys": ["ledger"]}` |
| `GET /api/desktop/plugin-data/{plugin_id}/{key}` | 返回原始 JSON；不存在 404 |
| `PUT .../{key}` | 请求体即 JSON 值；`{"ok": true}` |
| `DELETE .../{key}` | 幂等 204 |

规则：插件必须声明 `storage` 权限且处于启用状态（否则 403）；key 匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`；单值 ≤256KiB；落盘 `~/.desktop-app/plugin-data/<plugin_id>/<key>.json`（原子写）；卸载插件不清理数据。

## 5. `window.desktop` 能力表

| 能力 | 签名 | 权限 |
| --- | --- | --- |
| `storage` | `get(key, fallback?) / set(key, value) / delete(key) / keys()`，全异步 | `storage` |
| `tools` | `register(defs, handlers) / unregister(names)` | `tools` |
| `notify` | `notify(title, body?)` 或 `notify({title, body})` | `notify` |
| `settings` | `get/set`，同步，存 localStorage（`desktop:settings:`） | `settings` |
| `events` | `on/emit`，postMessage 同窗口 | `events` |
| `http` | `get/post...`，经宿主 `/api/desktop/proxy` | `http` |
| `platform` | `info()` 等 | `platform` |
| `log` | `debug/info/warn/error` | `log` |
| 通用 | `ready` / `pluginId` / `pluginName` / `appInfo` / `getApps` / `navigate` / `openApp` | 无 |

## 6. 真实模型接入

宿主配置 `~/.desktop-app/agent.json`（0600，仅宿主进程可读）：

| 字段 | 说明 |
| --- | --- |
| `baseUrl` | AI Base 地址，如 `http://127.0.0.1:8000` |
| `clientId` / `clientSecret` | Embed Client 凭据（secret 只留宿主） |
| `agentId` | 要连的 Agent ID |
| `hostToolNames` | 换 token 时声明的工具名，缺省取本子应用方法名 |

接口：

- `GET /api/desktop/agent-config` → `{enabled, mode: "remote"|"dev", baseUrl, clientId, agentId, hostToolNames, hasSecret}`（不含 secret）
- `PUT /api/desktop/agent-config` → 保存（secret 留空沿用旧值，首次必填）
- `DELETE /api/desktop/agent-config` → 清除，回落到本地 mock 网关
- `POST /api/desktop/agent-token` `{origin}` → `{token, expiresIn, endpoint, platformId, agentId, displayName}`；origin 只接受 `http://127.0.0.1|localhost|::1:<port>`

一次性把模型侧配置写好（管理员账号，幂等）：

```bash
python apps/desktop/scripts/configure_ai_base.py --dry-run   # 先看变更
python apps/desktop/scripts/configure_ai_base.py             # 落库 + 双绑定
```

它做三件事：并入 `allowed_origins`（默认 `http://127.0.0.1:8765` + `http://127.0.0.1:8443`）→ 按 `tools.json` upsert `HostToolPolicy` 并 `PATCH is_enabled` → `PUT` 绑定到 Agent 与 Embed Client。参数：`--api-base/--account/--password/--platform-id/--agent-id/--client-id/--tools/--origin/--confirm-financial/--dry-run`，默认值读 `~/.desktop-app/agent.json` 与 `EMBED_*` 环境变量。

本地闭环（不接后端）：`DESKTOP_DEV_AGENT=1` 启动宿主，`GET /api/desktop/dev-agent/session` 返回 `{endpoint: "/api/v1/ws/agents/local", ...}`，WS 子协议 `ai-agent.v1`、token `dev-local-token`，规则式回复，仅用于无网调试。

## 7. 验证探针骨架

预挂载（证明「不点开子应用也有方法」）：

```bash
HOME="$PROBE/home" node apps/ledger/scripts/install-to-desktop.mjs \
  --target "$PROBE/home/.desktop-app/plugins/ledger" --json
HOME="$PROBE/home" PYTHONPATH=apps/desktop DESKTOP_DEV_AGENT=1 \
  python -c "import logging, uvicorn; logging.basicConfig(level=logging.INFO); uvicorn.run(create_app(), port=8796)"
# 另开进程：宿主首页不带 hash，抓注册日志
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --virtual-time-budget=15000 --dump-dom http://127.0.0.1:8796/ 2>&1 \
  | grep -E "收到宿主工具注册.*ledger_add_entry"
```

WS 回环：`websockets.connect(ws_url, subprotocols=["ai-agent.v1"], proxy=None)`（有代理环境变量时必须显式 `proxy=None`）→ `auth` → `host_tools_register` → `message_send` → 断言收到 `host_tool_call` 且 `arguments` 正确 → 回 `host_tool_result` → 断言 `message_completed`。

真实模型探针：`POST {baseUrl}/api/v1/embed/tokens` 换 token（origin 必须是已登记来源）→ 连 `ws://<host>:8000/api/v1/ws/agents/<agentId>` → 发一句自然语言 → 断言模型调用了你的方法名（不要写死「第 N 次调用是哪个工具」，模型顺序不固定）。

## 8. 新增子应用的改动清单

| 位置 | 改动 |
| --- | --- |
| `apps/<name>/` | 子应用工程 + `tools.json` + `public/manifest.json` + `scripts/install-to-desktop.mjs` |
| `pnpm-workspace.yaml` | 追加 `- 'apps/<name>'` |
| `apps/desktop/desktop_app/agent_config.py` | 若工具名集合变化，更新 `DEFAULT_HOST_TOOL_NAMES` |
| `apps/desktop/scripts/configure_ai_base.py` | 用 `--tools apps/<name>/tools.json` 指向新契约 |
| `apps/desktop/README.md` | 补子应用小节与方法列表 |
| `docs/CHANGELOG.md` | 一条 `feat:` 记录 |
| `docs/harness/requests/<date>-<topic>/spec.md` + `tools/harness/verify/<id>.sh` | 跨 `apps/` 改动属 B 档，必须先确认后实现 |
