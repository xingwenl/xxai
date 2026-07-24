# 实施计划

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
