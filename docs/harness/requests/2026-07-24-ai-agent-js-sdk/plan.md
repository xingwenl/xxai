# 实施计划

## 2026-07-31 增量实施计划

### 变更文件

- 修改：`apps/ai-sdk/src/core/types.ts`，定义 `TokenProviderContext` 并更新 `getToken` 类型。
- 修改：`apps/ai-sdk/src/core/client.ts`，把用户和平台上下文传递给传输层。
- 修改：`apps/ai-sdk/src/core/websocket.ts`，每次认证调用 token provider，校验空 token，并保持既有 auth 帧结构。
- 修改：`apps/ai-sdk/src/core/__tests__/websocket.test.ts`，覆盖上下文、空 token 和重连重新取 token。
- 修改：`apps/ai-sdk/README.md`、`docs/runbooks/agent-sdk-local-integration.md`，解释 Embed Token、`external_user_id` 来源和生产/本地边界。
- 修改：本 request 的 `research.md`、`spec.md`、`verify.md`、`acceptance.md`、`meta.json`。

### 实施步骤

1. 先在 WebSocket 测试中写出 provider 接收上下文、空 token 拒绝和重连重新取 token 的失败断言，并运行单测确认失败原因是缺少新行为。
2. 增加 `TokenProviderContext` 类型，让 `AgentClient` 将 `platformId`、`agentId` 和可选 `user` 传递到 `WebSocketTransport`。
3. 更新 `WebSocketTransport.authenticate`，每次调用 `getToken(context)`；对非空字符串执行现有 auth 发送，对空白 token 抛出稳定错误且不发送 auth 帧。
4. 更新 README 与联调手册，给出生产 token 代理伪代码，明确服务端从登录态取得 `external_user_id`；保留 Demo 代理但标记为本地用途。
5. 运行 SDK 单测、类型检查、构建和后端 Embed 回归测试，并把真实命令和结果写入 `verify.md`。

### 回滚方式

撤回本次增量时恢复 SDK 的 `getToken: () => Promise<string>` 类型及对应文档/测试；不涉及数据库迁移和后端运行时代码，因此不需要数据回滚。

### 人工确认

本次涉及 SDK token provider API 和鉴权接入语义，已在进入实现前获得人工确认；不新增数据模型、不修改 JWT claims、不修改 WebSocket 协议字段。

## 变更文件

- 列出将新增、修改的文档或代码文件
  - 新增：`apps/ai-sdk/package.json` - 项目配置
  - 新增：`apps/ai-sdk/tsconfig.json` - TypeScript 配置
  - 新增：`apps/ai-sdk/vite.config.ts` - Vite 打包配置
  - 新增：`apps/ai-sdk/src/index.ts` - SDK 入口
  - 新增：`apps/ai-sdk/src/core/types.ts` - 类型定义
  - 新增：`apps/ai-sdk/src/core/client.ts` - AgentClient 主类
  - 新增：`apps/ai-sdk/src/core/event-emitter.ts` - 事件系统
  - 新增：`apps/ai-sdk/src/core/message-store.ts` - 消息存储
  - 新增：`apps/ai-sdk/src/core/tool-registry.ts` - 工具注册表
  - 新增：`apps/ai-sdk/src/core/transport.ts` - 传输层抽象
  - 新增：`apps/ai-sdk/src/core/websocket.ts` - WebSocket 实现
  - 新增：`apps/ai-sdk/src/ui/index.ts` - UI 入口
  - 新增：`apps/ai-sdk/src/ui/components/ChatWidget.vue` - 悬浮聊天组件
  - 新增：`apps/ai-sdk/src/ui/components/ChatBubble.vue` - 消息气泡
  - 新增：`apps/ai-sdk/src/ui/components/ChatInput.vue` - 输入框
  - 新增：`apps/ai-sdk/src/ui/components/ChatMessageList.vue` - 消息列表
  - 新增：`apps/ai-sdk/src/ui/components/FloatingButton.vue` - 悬浮按钮
  - 新增：`apps/ai-sdk/src/ui/styles/index.css` - 样式
  - 新增：`apps/ai-sdk/demo/index.html` - Demo 页面
  - 新增：`apps/ai-sdk/README.md` - 项目说明
  - 修改：`docs/harness/requests/2026-07-24-ai-agent-js-sdk/meta.json` - 更新 phase
  - 修改：`docs/harness/requests/2026-07-24-ai-agent-js-sdk/verify.md` - 验证记录
  - 修改：`docs/harness/requests/2026-07-24-ai-agent-js-sdk/acceptance.md` - 验收记录
- 说明每个文件承担的职责
  - 遵循分层架构：core（纯 TypeScript）、ui（Vue 组件）
- 说明实施步骤如何落实 `research.md` 中选择的方案
  - 实现方案 A（核心+UI 层合一）
  - 参考 agentpage 的回调系统设计
  - 使用 TypeScript + Vue 3 + Vite

## 实施步骤

1. 初始化项目结构
   - 创建 `apps/ai-sdk` 目录
   - 初始化 `package.json`、`tsconfig.json`、`vite.config.ts`
   - 安装依赖：vue、typescript、vite、@vitejs/plugin-vue

2. 实现 core 层
   - 编写 `types.ts` 类型定义
   - 编写 `event-emitter.ts` 事件系统
   - 编写 `message-store.ts` 消息存储
   - 编写 `tool-registry.ts` 工具注册表（预留）
   - 编写 `transport.ts` 传输层抽象
   - 编写 `websocket.ts` WebSocket 实现（含 mock）
   - 编写 `client.ts` AgentClient 主类
   - 编写 `core/index.ts` 导出

3. 实现 ui 层
   - 编写 Vue 组件：FloatingButton、ChatWidget、ChatBubble、ChatInput、ChatMessageList
   - 编写样式
   - 编写 `ui/index.ts` 导出，含 registerCustomComponent

4. 实现 SDK 入口
   - 编写 `src/index.ts`，整合 core 和 ui
   - 导出 createAgentClient 工厂函数

5. 编写 Demo
   - 创建 demo/index.html
   - 演示 SDK 使用方法

6. 配置打包
   - 配置 Vite 输出 ESM 和 UMD
   - 测试打包

## 测试步骤

- 写明计划执行的命令
  - `cd apps/ai-sdk && npm install`
  - `npm run build` - 验证打包
  - `npm run dev` - 启动 demo 验证功能
- 写明预期结果
  - 打包成功，无错误
  - Demo 页面能正常加载和交互
- 若当前阶段无法执行，也提前说明原因

## 回滚说明

- 说明如何撤回本次改动
  - 删除 `apps/ai-sdk` 目录
  - 删除 `docs/harness/requests/2026-07-24-ai-agent-js-sdk` 目录
- 说明哪些文件或行为需要特别关注
  - 无，全新项目

## 人工确认点

- 列出必须等待人工确认的步骤或设计点
  - 实施前确认 spec.md 设计方案（已触发停点）
  - 实施完成后确认验收结果
- 若本次无人工确认点，明确写“无”
