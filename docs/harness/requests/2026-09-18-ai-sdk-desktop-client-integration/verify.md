# 验证记录

验证时间：2026-09-18
验证环境：macOS（Apple Silicon）、Node v20.19.5、Python 3.12（poetry venv）、pnpm 9.15.9

## 1. 后端（本仓库）

### 1.1 增量子集

```bash
cd apps/backend && poetry run pytest tests/shop_agent tests/embed tests/gateway tests/system -q
```

结果：`136 passed, 1 skipped, 1 warning in 6.36s`。

### 1.2 全量回归

```bash
cd apps/backend && poetry run pytest -q --import-mode=importlib
```

结果：`652 passed, 1 skipped, 4 warnings in 12.58s`。

> 说明：全量必须带 `--import-mode=importlib`；不带时 `tests/` 下存在同名测试模块（如多个 `test_router.py`）导致收集期报错，属于本次改动前既有问题。

### 1.3 新增测试覆盖点

| 文件 | 用例数 | 覆盖内容 |
| --- | --- | --- |
| `apps/backend/tests/shop_agent/test_session_params.py` | 6 | `agentId`/`hostToolNames` 的别名解析、默认值、缺省回退服务端默认 Agent、越界值被拒、向 `issue_configured_agent_token` 的透传 |
| `apps/backend/tests/system/test_cors_config.py` | 4 | 默认来源与改动前逐条一致、`CORS_ORIGINS` 逗号分隔解析、去重与去尾斜杠、空值回退默认 |

> 计划文档写作 `tests/core/test_cors_config.py`，实际落在已有的 `tests/system/` 目录（该目录已承载同类配置类测试），用例内容与计划一致。

## 2. AI SDK 文档（本仓库）

`apps/ai-sdk/README.md` 新增第 15 章「桌面客户端（Electron）接入」（15.1–15.6）与第 15.6 节「后台策略与前端注册的 Schema 对齐」。本次只改文档，未改 SDK 源码。

```bash
cd apps/ai-sdk && npm run type-check
```

结果：失败于 `src/ui/__tests__/chat-message.ssr.test.ts(3,32): Cannot find module '@vue/server-renderer'`。
该文件最后修改于提交 `7694ad8`，且本次仅改动 `README.md`（`git status --short apps/ai-sdk` 只有 `M apps/ai-sdk/README.md`），因此判定为**既有失败**，与本次改动无关。

## 3. 接入方（跨仓：`/Users/lixingwen/xw/zhoudan/client/operations-desktop`）

### 3.1 类型检查与构建

| 命令 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过（无输出） |
| `npm run build`（typecheck + vite build + tsc electron + preload 拷贝） | 通过；SDK 被拆分为独立 chunk `dist/renderer/assets/xxai-agent.es-C2st6dU0.js`（286.95 kB），仅在打开智能体标签页时按需加载 |
| `npm run build:electron` | 通过 |

### 3.2 单测

```bash
cd /Users/lixingwen/xw/zhoudan/client/operations-desktop && npm test
```

改动前基线：`1191 passed / 8 failed`（5 个文件）。
改动后：`collected 1233 / passed 1224 / failed 9`（用例总数 1199 → 1233，净增 34 条，全部为本次新增用例）。

新增 8 个测试文件、34 条用例全部通过（34 条即本次全量净增数；另有 2 个既有文件内改写了 3 条断言，不改变用例总数）：

| 文件 | 用例数 | 覆盖内容 |
| --- | --- | --- |
| `tests/agent-contract.test.ts` | 4 | 首批 4 个只读工具命名固定；`inputSchema` 规范化 sha256 指纹与 AI Base 后台策略常量逐条一致；`get_current_shop` 不接受模型参数；参数类型/区间/未知字段校验 |
| `tests/agent-config.test.ts` | 7 | 默认直连 `https://hua8.bbtree.xyz`；未配置 Agent 时降级为可读提示；生成 `wss` 网关地址与 API 根路径；保留站点子路径；非法 Agent ID / 非法站点地址不抛错 |
| `tests/agent-session.test.ts` | 5 | 请求地址带 `origin`；请求体只含平台登录态与工具候选、不含 `client_secret`；成功只回传短期 token；401 与网络异常的中文错误 |
| `tests/agent-tools.test.ts` | 5 | `get_current_shop` 返回当前店铺与各平台登录态、无选中时返回 `null`；`list_shops` 关键词与分页；`get_session_health` 统计与异常列表、非法平台被拒；`list_local_tasks` 取最近一次执行并按状态过滤 |
| `tests/agent-ipc.test.ts` | 4 | 非登记来源被拒；未登录时全部通道被拒且不换取会话；会话通道平台 token 只留在主进程；工具通道只接受登记的只读工具并携带工作台上下文 |
| `tests/agent-panel.test.tsx` | 4 | 无桥接/未配置时提示且不加载 SDK；连接时注册 4 个只读工具、复用首次 token、以 `embedded` 模式挂载；连接失败提示；卸载销毁客户端 |
| `tests/assistant-panel-agent-tab.test.tsx` | 1 | 未打开店铺页面也能切到「AI 智能体」标签并渲染面板 |
| `tests/renderer-server.test.ts` | 4 | 只监听回环地址、入口页 `no-store`；静态资源类型；无扩展名路径回退入口页、缺失资源 404；越权路径与非只读方法被拒 |
| `tests/electron-runtime.test.ts`、`tests/renderer-build.test.ts` | 改写 3 条 | 生产环境由 `file://` 改为固定 http origin 的断言 |

失败用例对照（改动后 9 条）：

- 8 条为改动前基线即存在的失败：`electron-runtime`（主进程源码断言）、`package-config`（`dist:win` 脚本与测试期望不一致）、`structured-order-payload`、`unified-shop-panel`（2 条）、`workbench-dashboard`（3 条）。
- 1 条为并行全量下的偶发失败（`app-shell` 的滚动/进度相关用例），单独运行通过：`npx vitest run tests/app-shell.test.tsx` → `40 passed`；同一用例在其他两次全量运行中通过。已在 `acceptance.md` 记为残留噪声。

### 3.3 身份字段核对（已完成）

`external_user_id` 取 hua8（花伴）用户 ID，链路已核对：

- 来源：`electron/core/huaban-auth-client.ts` 调用 `https://hua8.bbtree.xyz/hua8-api/system/user/getInfo`，取 `user.userId ?? user.user_id` 作为 `userId` 写入登录态；
- 类型契约：`src/shared/auth.ts` 的 `AuthenticatedUser.userId`（必填 `string`）；
- 使用点：`electron/main.ts` 组装登录态时返回 `{ accessToken, userId, displayName }`，`electron/agent-session.ts` 再把它作为 `shopUserId` → 后端 `external_user_id`。

结论：`userId` 是 hua8 账号维度稳定标识，与 `apps/shop` 的 `ChatPage.vue` 取值口径一致（同为花伴登录态用户 ID），可作为 Embed 会话的外部用户标识。

### 3.4 未能执行的验证（需人工环境）

以下项需要 AI Base 运行实例、hua8 可用账号与后台配置，本次未执行：

1. 真机端到端：Electron 中以 `http://127.0.0.1:5390` 加载、完成一轮真实问答；
2. 通过店铺工具读取 hua8 数据（依赖 `STORE_OPS_BASE_URL` 与 hua8 账号）；
3. 4 个桌面只读工具被模型成功调用（依赖后台创建工具策略并把 schema 指纹对齐、把工具绑定到 Agent 与 Embed Client、把桌面 origin 加入 `allowed_origins`）。

以上各项的解除条件与操作步骤见 `acceptance.md` 的「待人工执行」小节（含后台 Agent/工具策略/来源登记清单与桌面端配置项）。

## 3.5 第 3 次增量验证（验收后补充）

变更：`shop-agent/session` 新增可选 `clientId` / `clientSecret`，透传给 `issue_configured_agent_token`；缺省回退服务端 env 配置。

```bash
cd apps/backend && poetry run pytest tests/shop_agent/test_session_params.py -q
```

结果：`13 passed`（该文件由 5 条增至 12 条用例，其中 1 条为参数化展开，合计 13 项）。

```bash
cd apps/backend && poetry run pytest tests/shop_agent tests/embed tests/gateway tests/system -q
```

结果：`144 passed, 1 skipped`（变更前为 136 passed）。

```bash
cd apps/backend && poetry run pytest -q --import-mode=importlib
```

结果：`660 passed, 1 skipped`（变更前为 652 passed）。

新增用例覆盖：CamelCase 凭证解析、凭证可选、成对透传并按其 `client_id` 查找 Client、缺省沿用 env Client、只传其一被拒、携带凭证未传 `agent_id` 被拒、携带凭证未传 `origin` 被拒。

## 3.6 第 4 次增量验证（验收后补充）

变更：`shop_agent/router.py` 新增 `PROJECT_EMBED_*` 常量，取值优先级为「请求凭证 > 项目常量 > 环境变量」。

```bash
cd apps/backend && poetry run pytest tests/shop_agent -q
```

结果：`24 passed`（原 19；新增 5 条接口层用例，覆盖常量兜底、常量生效、项目来源补齐、固定 Client 缺 Agent 时 400、请求凭证优先于常量）。

```bash
cd apps/backend && poetry run pytest -q --import-mode=importlib
```

结果：`665 passed, 1 skipped`（变更前 660 passed）。

## 3.7 桌面端首次真机联调排障（2026-09-19）

现象：桌面端 `agent:session` 报「未能获取智能体会话凭证，请重新登录」。

定位（本机探测 hua8）：

```bash
curl -s -m 10 -X POST 'https://hua8.bbtree.xyz/api/v1/shop-agent/session?origin=http://127.0.0.1:5390' \
  -H 'Content-Type: application/json' -d '{"shopToken":"x","shopUserId":"1"}'
```

结果：`status=200`、`{"code":500,"msg":"404 NOT_FOUND \"No static resource api/v1/shop-agent/session.\""}`。

结论：`https://hua8.bbtree.xyz` 是 hua8 平台自身的后端，不是 AI Base；接入方默认的 `DEFAULT_AGENT_BASE_URL` 填成了业务平台地址。业务平台习惯以 HTTP 200 + `{code,msg}` 返回自身的 404，客户端匹配不到 AI Base 的 `success/data` 信封，于是抛出与实际原因无关的兜底提示。

处置（接入方仓库）：

- `electron/agent-config.ts`：`DEFAULT_AGENT_BASE_URL` 改为空，未配置时降级为「尚未配置 AI Base 地址」的中文指引，不再默认指向业务平台；
- `electron/agent-session.ts`：错误提取兼容业务平台的 `msg`，并在响应不是 AI Base 信封时明确提示检查 `OPERATIONS_AGENT_BASE_URL`；
- 单测：`tests/agent-config.test.ts`、`tests/agent-session.test.ts`（含新增「地址填成业务平台」用例）共 `17 passed`（含 `agent-panel`）；`npm run typecheck` 通过。

待接入方确认：AI Base 的实际站点根（本地部署为 `http://127.0.0.1:8000`）尚未填写。

## 4. 结论

- 本仓库改动：**已通过**（全量 665 passed；第 3、4 次增量见 3.5、3.6）。
- 接入方改动：**编译与单测通过**，无新增确定性失败；端到端联调属未执行项。
- 验证方式以单测 + 构建为主，缺少真实链路证据，因此验收结论为「条件通过」。
