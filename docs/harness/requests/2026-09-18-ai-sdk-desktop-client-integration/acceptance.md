# 验收结论

验收时间：2026-09-18
验收结论：**条件通过** —— 代码与文档已完成并通过可自动化的验证；真实链路（AI Base + hua8 + 桌面端）联调属未执行项，需按下文「待人工执行」完成后转为完全通过。

## 1. 交付物

### 1.1 本仓库（ai-base）

| 文件 | 变更 |
| --- | --- |
| `apps/backend/app/modules/embed/services.py` | `issue_configured_agent_token` 新增可选 `agent_id`（缺省回退 `settings.embed_agent_id`）与 `host_tool_names` 透传 |
| `apps/backend/app/modules/shop_agent/schemas.py` | `ShopAgentSessionRequest` 新增 `agentId`、`hostToolNames`、`clientId`、`clientSecret`（均向后兼容） |
| `apps/backend/app/modules/shop_agent/router.py` | 透传上述两个参数 |
| `apps/backend/app/core/config.py` | 新增 `cors_origins`，读取 `CORS_ORIGINS`（逗号分隔），默认值与改动前逐条一致 |
| `apps/backend/app/__init__.py` | `CORSMiddleware` 改用 `settings.cors_origins` |
| `apps/backend/tests/shop_agent/test_session_params.py` | 新增 6 条用例 |
| `apps/backend/tests/system/test_cors_config.py` | 新增 4 条用例 |
| `apps/ai-sdk/README.md` | 新增第 15 章「桌面客户端（Electron）接入」（15.1–15.6） |
| `docs/CHANGELOG.md` | 记录本次变更 |

### 1.2 接入方仓库（`/Users/lixingwen/xw/zhoudan/client/operations-desktop`）

| 文件 | 变更 |
| --- | --- |
| `electron/renderer-server.ts` | 新增：只监听 `127.0.0.1:5390` 的静态服务，`no-store`、路径越界防护、SPA 回退 |
| `electron/renderer-target.ts` | 生产环境由 `file://` 改为 `http://127.0.0.1:5390`；新增 `resolveRendererRoot` |
| `electron/main.ts` | 建窗前启动静态服务、退出时释放；注册智能体 IPC |
| `electron/agent-config.ts` | 新增：智能体运行时配置（站点、Agent、来源、工具候选） |
| `electron/agent-session.ts` | 新增：主进程用 hua8 登录态换取 embed token |
| `electron/agent-tools.ts` | 新增：4 个只读工具的执行实现 |
| `electron/agent-ipc.ts` | 新增：`agent:config` / `agent:session` / `agent:tool` 通道 |
| `electron/preload.cjs` | 暴露 `cookieOperations.agent` |
| `src/shared/agent-ipc.ts` | 新增：跨进程契约（通道、工具 schema 与指纹、参数校验） |
| `src/shared/workspace-ipc.ts` | 新增 `accountStoreId`，把「账号 → 店铺 ID」约定收敛到共享模块 |
| `src/domain/workspace-mapper.ts` | 复用 `accountStoreId` |
| `src/desktop/agent-client.ts`、`src/desktop/store-directory-client.ts` | 新增桥接客户端并扩展 `window.cookieOperations` 类型 |
| `src/components/AgentChatPanel.tsx`、`src/components/AssistantPanel.tsx`、`src/styles/workbench.css` | 右侧助手区新增「AI 智能体」标签页并挂载 SDK（`ui.mode: 'embedded'`） |
| `src/types/xxai-agent.d.ts` | SDK 子路径样式模块类型声明 |
| `tests/*`（8 个新增文件，34 条用例） | 契约、配置、会话、工具、IPC、面板、静态服务 |
| `package.json`、`pnpm-lock.yaml` | 新增依赖 `xxai-agent@0.1.6` |

两个仓库均**未提交**，由用户决定提交时机与粒度。

## 2. 验收标准逐条对照

| 验收标准（`spec.md`） | 结论 | 依据 |
| --- | --- | --- |
| 不传 `agent_id` 时 `shop-agent/session` 行为与改动前一致 | 通过 | `test_session_params.py` 覆盖缺省回退；`apps/shop` 既有调用方未改动 |
| 传入已绑定 Agent 时签发对应 token，未绑定则拒绝 | 部分通过（依赖既有 `is_agent_allowed` 分支，未新增用例） | `issue_embed_token` 既有校验路径 + 透传用例 |
| CORS 默认值与改动前一致，配置后可新增桌面来源 | 通过 | `test_cors_config.py` 4 条用例 |
| 来源校验不变，`file://` 仍被拒 | 通过 | `allowed_origins` 与 `create_embed_token` 未改动；桌面端改为 http origin 后不再依赖 `file://` |
| 桌面端以固定 http origin 加载成功，导航守卫行为不变 | 通过（单测层面） | `electron-runtime.test.ts` 改写后通过；`renderer-server.test.ts` 4 条用例 |
| `host_tool_names` 空值/交集/未绑定名称语义 | 通过 | 交集逻辑在 `issue_embed_token` 内未改动；新增透传用例 |
| 端到端：真实问答 + 店铺工具 + 至少一个桌面只读工具 | **未执行** | 需要 AI Base 实例、hua8 账号与后台配置 |
| 渲染层不出现 `client_secret`，hua8 token 不下发渲染层 | 通过 | `agent-session.test.ts` 断言请求体与返回值均不含 `client_secret`／平台 token；`agent-ipc.test.ts` 断言渲染层只拿到 `access_token` |
| 文档与测试 | 通过 | README 第 15 章、CHANGELOG；后端 665 passed |

## 2.1 第 3 次增量（验收后补充）

- 变更：`shop-agent/session` 支持调用方携带自己的 Embed Client 凭证（`clientId` / `clientSecret`），透传给 `issue_configured_agent_token`；缺省回退服务端 `EMBED_*` 配置，既有调用方零改动。
- 语义：凭证必须成对提供；携带凭证时必须显式给出 `agentId` 与 `origin`；目标 Client 的 `allowed_origins`、Agent 绑定、工具绑定与配额逐条生效。
- 验证：`tests/shop_agent/test_session_params.py` 13 passed；增量子集 144 passed；全量 660 passed（详见 `verify.md` 3.5）。
- 安全边界：凭证等同于签发权限，只能由可信服务端持有；若把它塞进 Electron 包内，等于下发签发权限，不建议。

## 2.2 第 4 次增量（验收后补充）

- 变更：`shop_agent/router.py` 新增 `PROJECT_EMBED_CLIENT_ID` / `PROJECT_EMBED_CLIENT_SECRET` / `PROJECT_EMBED_AGENT_ID` / `PROJECT_EMBED_ORIGIN` 常量，凭证固定留在服务端。
- 优先级：请求携带的凭证 > 项目常量 > `EMBED_*` 环境变量；常量留空时行为与变更前一致。
- 校验：固定 Client 时必须同时配 Agent 与来源，否则 400。
- 验证：`tests/shop_agent` 24 passed；全量 665 passed（详见 `verify.md` 3.6）。
- 使用方式：创建好该项目专用的 Embed Client 后，把 `client_id` 与 `client_secret` 填进上述常量（密钥会随源码进入版本库，如需避免则改用环境变量），Agent 与来源填该项目对应的值。

## 3. 待人工执行（转为完全通过的条件）

### 3.1 AI Base 后台

1. 新建桌面端 Agent（与网页端 Agent 分开），记录 `agent_id`；
2. 把该 Agent 绑定到与 shop 相同的 Embed Client；
3. 创建 4 个宿主工具策略并把 `input_schema` 逐字对齐（**必须与前端注册完全一致，否则被静默忽略**）：

| 工具名 | `input_schema` | 指纹（sha256） |
| --- | --- | --- |
| `get_current_shop` | `{"type":"object","properties":{},"additionalProperties":false}` | `99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa` |
| `list_shops` | `{"type":"object","properties":{"keyword":{"type":"string"},"limit":{"type":"integer"}},"additionalProperties":false}` | `b5498e7cd696fdec4c0282d60f5f3d595eaf862425fe7806d87d81cc8d5c3e39` |
| `get_session_health` | `{"type":"object","properties":{"platform":{"type":"string"}},"additionalProperties":false}` | `11da5b1dfb0962a6a936d9f01531060d5a05384f59f58f374b53ab6c28646be0` |
| `list_local_tasks` | `{"type":"object","properties":{"status":{"type":"string"},"limit":{"type":"integer"}},"additionalProperties":false}` | `c506136f7b08cd50b699c8fce14c0b920825baca6002dfdd97267860e7fc0b12` |

4. 把 4 个工具策略绑定到该 Agent **与** 该 Embed Client（网关取「token claim ∩ Agent 绑定 ∩ 页面注册」）；
5. 把桌面来源 `http://127.0.0.1:5390`（以及在 5190 启动 dev 时的 `http://127.0.0.1:5190`）加入该 Embed Client 的 `allowed_origins`。

### 3.2 AI Base 部署配置

- `STORE_OPS_BASE_URL`：指向 hua8（当前实现为 `https://hua8.bbtree.xyz`）；
- `EMBED_CLIENT_ID` / `EMBED_CLIENT_SECRET` / `EMBED_AGENT_ID` / `EMBED_ORIGIN`：与上述 Embed Client 和 Agent 对应；
- `CORS_ORIGINS`：在既有来源基础上追加 `http://127.0.0.1:5390`（否则聊天可用，但附件上传/下载等 HTTP 接口会被浏览器拦截）。

### 3.3 桌面端

- 把新建的 Agent ID 填入接入方 `electron/agent-config.ts` 的 `DEFAULT_AGENT_ID`，或以环境变量 `OPERATIONS_AGENT_ID` 覆盖（另有 `OPERATIONS_AGENT_BASE_URL`、`OPERATIONS_AGENT_PLATFORM_ID`）；
- 启动应用（生产模式默认 `http://127.0.0.1:5390`），打开右侧助手「AI 智能体」标签，完成一轮真实问答；
- 触发 `store_ops_query` 与至少一个只读桌面工具，确认返回真实数据；
- 若工具未被调用，按 README 15.6 的排障顺序检查 token claim 与服务端日志。

## 4. 剩余风险

1. **未做真机联调**：加载链路、token 换取、工具注册三条链路都只有单测证据，首次联调仍可能暴露环境相关问题（harbor 配置、网络、账号权限）。
2. **桌面来源是本地端口**：本机任意程序都可监听同一端口，访问控制实际依赖 token 签发环节；这也是没有把 `client_secret` 放进客户端的直接收益。
3. **CORS 放宽**：新增来源意味着该来源的页面可携带凭证访问 AI Base 的 HTTP 接口，需确保只为受控来源登记。
4. **并行测试噪声**：接入方全量在并行负载下存在 1 条偶发失败（`app-shell`），与本次改动无关，单独运行稳定通过。
5. **既有失败未修复**：本仓库无新增失败；接入方 8 条既有失败（`electron-runtime` 源码断言、`package-config`、`structured-order-payload`、`unified-shop-panel`、`workbench-dashboard`）按约定不在本次范围内修复。

## 5. 回滚方式

- 后端：还原 5 个改动文件即可；`agent_id` 缺省回退与 `host_tool_names` 缺省空列表保证既有调用方行为不变。
- CORS：删除 `CORS_ORIGINS` 即回到默认四项。
- 接入方：还原 `electron/renderer-target.ts` 与 `electron/main.ts` 的加载方式即可回到 `file://`（代价是 AI 面板不可用）；其余为新增文件，删除即回滚。
- 回滚后需重新确认窗口能正常加载与导航（属启动关键路径）。
