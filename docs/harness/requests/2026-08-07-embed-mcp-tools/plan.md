# Embed 对话接入 MCP 工具实施计划

## 目标

在现有 Embed WebSocket 与 `apps/ai-sdk` 中完成 MCP 工具可见、后端执行、副作用确认、原对话恢复和双主体审计闭环，同时保持 REST 对话、Skill、内置工具和宿主工具行为兼容。

## 实施边界

- 基于当前工作区已存在的 `runtime_tools` 与内置工具改动继续实现，不回退或覆盖 `2026-08-07-builtin-http-get` 的未提交内容。
- 不修改 MCP 管理 API、工具同步与 Agent 绑定契约。
- 不升级 MCP Python SDK。
- 不提交与本 request 无关的文件。

## Task 1：双主体 MCP 审计与确认

**文件：**

- 修改 `apps/backend/app/modules/mcp/models.py`
- 修改 `apps/backend/app/modules/mcp/schemas.py`
- 修改 `apps/backend/app/modules/mcp/repositories.py`
- 修改 `apps/backend/app/modules/mcp/services.py`
- 新增 `apps/backend/migrations/versions/20260807_0020_embed_mcp_principal.py`
- 修改/新增 `apps/backend/tests/mcp/` 定向测试

**步骤：**

1. 先增加失败测试，覆盖后台用户主体、Embed 最终用户主体、两者同时存在和两者同时为空。
2. 将 audit/confirmation 的 `user_id` 改为可空并增加带中文 comment 的 `platform_end_user_id`。
3. 增加 XOR CheckConstraint、外键和索引；迁移保持已有 `user_id` 数据不变，并提供可逆 downgrade。
4. 将 repository/service 调整为显式 principal 参数，查询确认时校验正确主体。
5. 增加确认过期服务，使 confirmation 与 audit 原子收敛到 `expired`。

## Task 2：Gateway 统一工具注册、分流和确认恢复

**文件：**

- 修改 `apps/backend/app/modules/gateway/router.py`
- 修改 `apps/backend/app/modules/gateway/runtime.py`
- 必要时修改 `apps/backend/app/modules/conversation/runtime.py`
- 修改 `apps/backend/tests/gateway/test_chat_flow.py`
- 修改/新增 Gateway WebSocket 定向测试

**步骤：**

1. 增加测试证明 `context.mcp_tools` 自动加入 Embed `runtime_tools`，无需逐个 MCP 写死。
2. 建立显式工具来源识别与冲突过滤；同名冲突全部排除，其他工具保留。
3. 将当前 `invoke_host_tool` 收敛为运行时工具调度器，分别处理 builtin、MCP、Skill 和 Host Tool。
4. MCP 只读工具调用现有 `invoke_tool()` 并把结果回填原模型循环。
5. MCP 高风险工具创建 confirmation 后，Gateway 发送通用 `confirmation_required`、等待连接级 Future，并在 `confirmation_resolve` 后调用 `resolve_tool_confirmation()`。
6. 批准、拒绝、超时和断线都生成稳定工具结果；副作用调用不自动重试。
7. 协议载荷只发送脱敏参数、公共 `callId`、工具类型、副作用和过期时间。

## Task 3：SDK 协议、状态和内置确认 UI

**文件：**

- 修改 `apps/ai-sdk/src/core/protocol.ts`
- 修改 `apps/ai-sdk/src/core/types.ts`
- 修改 `apps/ai-sdk/src/core/client.ts`
- 修改 `apps/ai-sdk/src/core/websocket.ts`
- 修改 `apps/ai-sdk/src/ui/components/ChatWidget.vue`
- 新增 `apps/ai-sdk/src/ui/components/ToolConfirmation.vue`
- 修改 `apps/ai-sdk/src/ui/styles/index.css`
- 修改/新增 `apps/ai-sdk/src/core/__tests__/` 与 UI 测试

**步骤：**

1. 扩展 confirmation 类型，保留已有 `callId`、`name` 并增加 `toolType`、`sideEffect`、脱敏摘要和过期时间。
2. 客户端保存单个待确认对象并暴露给 UI；重复 resolve 不重复发送。
3. 未配置 `onConfirmationRequired` 时显示 SDK 内置确认面板；配置回调时不显示默认面板。
4. 确认面板展示工具名、风险等级和格式化参数，提供允许/拒绝按钮及提交中状态。
5. 组件卸载、连接关闭和请求结束时清理待确认状态。
6. 覆盖协议解析、默认 UI、自定义回调覆盖、重复点击和移动宽度布局测试。

## Task 4：前端 bridge 收敛

**文件：**

- 修改 `apps/front/src/features/agent-navigation/agent-navigation-bridge.tsx`
- 修改相关定向测试或构建配置（仅在需要时）

**步骤：**

1. 删除当前 `window.confirm` 和“非导航工具自动拒绝”逻辑。
2. 将 system prompt 从“只能调用导航工具”改为不扩大权限的通用后台助手说明。
3. 保持 `navigate_to_page` 注册和白名单导航行为不变。

## Task 5：验证、验收与回滚

**验证命令：**

- `cd apps/backend && poetry run pytest tests/mcp tests/gateway tests/conversation -q`
- `cd apps/backend && poetry run ruff check app/modules/mcp app/modules/gateway app/modules/conversation tests/mcp tests/gateway tests/conversation`
- `cd apps/backend && poetry run alembic upgrade head`
- `cd apps/backend && poetry run alembic downgrade -1 && poetry run alembic upgrade head`
- `cd apps/ai-sdk && pnpm test`
- `cd apps/ai-sdk && pnpm run typecheck`
- `cd apps/ai-sdk && pnpm run build`
- `cd apps/front && pnpm exec eslint src/features/agent-navigation/agent-navigation-bridge.tsx`
- `cd apps/front && pnpm run build`

**人工联调：**

1. 使用真实 Agent 和远程 MCP 只读工具，确认浮动对话可自动调用并继续回答。
2. 使用 `write` 或 `external` 工具，确认 SDK 面板显示脱敏参数。
3. 分别批准、拒绝、等待超时和断开 WebSocket，核对远程调用次数与审计终态。
4. 核对浏览器事件、服务端日志和模型提示中不存在 MCP 凭据。

**回滚：**

- 代码回滚必须同时撤回 Gateway MCP 调度、SDK confirmation UI 和双主体迁移，不能只回滚其中一层。
- downgrade 前确认不存在仅关联 `platform_end_user_id` 的 MCP audit/confirmation；若存在则保留迁移或先按数据保留策略导出，禁止静默删除审计事实。

## 人工确认

- 用户于 2026-08-07 审阅正式 `spec.md` 后回复“可以 批准实施”。
- 批准范围包括 Gateway 架构、MCP 双主体数据模型、WebSocket 契约、Embed 权限行为和 SDK 默认确认 UI。
