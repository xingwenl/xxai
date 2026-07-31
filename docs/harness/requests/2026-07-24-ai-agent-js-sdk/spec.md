# 设计说明

## 目标

- 说明本次 request 解决什么问题
  - 创建一个 AI Agent JS SDK，允许第三方网站快速嵌入 AI 聊天功能
  - 支持 headless 模式（纯编程接口）和 floating 模式（带 UI）
  - 支持消息管理、systemPrompt 设置
  - 预留工具注册和调用接口（第二阶段 B）
  - 预留 SSE 传输接口（未来支持）
- 说明目标用户、调用方或受影响对象
  - 第三方网站开发者
  - 前端集成人员
- 说明完成后应产生什么可验证结果
  - `apps/ai-sdk` 目录下完整的 SDK 项目
  - 可通过 npm 包或 CDN 引入
  - 包含 demo 页面演示功能
- 简要引用 `research.md` 的关键调研结论和最终方案
  - 参考 agentpage 的分层架构和回调系统
  - 选择方案 A（核心+UI 层合一）
  - 技术栈：TypeScript + Vue 3 + Vite

## 范围

- 明确本次包含的功能、接口、文档或配置项
  - ✅ 核心类型定义（types.ts）
  - ✅ AgentClient 主类（client.ts）
  - ✅ 事件系统（event-emitter.ts）
  - ✅ 消息存储（message-store.ts）
  - ✅ 工具注册表（tool-registry.ts，第二阶段 A 先预留）
  - ✅ WebSocket 传输层（transport.ts + websocket.ts）
  - ✅ SSE 传输层预留
  - ✅ Vue 3 UI 组件（floating 模式）
  - ✅ 可扩展消息内容（文本、图片、文本+按钮、自定义组件）
  - ✅ 打包配置（Vite，ESM + UMD）
  - ✅ Demo 页面
- 明确涉及的目录或模块
  - `apps/ai-sdk/`（全新创建）
- 若是增量任务，说明与原闭环的关系
  - 全新 request，无原闭环

## 非目标

- 写明这次不会顺手做的内容
  - ❌ 第二阶段 B：宿主工具完整实现（只预留接口）
  - ❌ 第二阶段 C：生产增强（断线续传、多标签协调等）
  - ❌ SSE 传输层完整实现（只预留接口）
  - ❌ embedded UI 模式（第一版只做 headless + floating）
  - ❌ React/Vue 包装组件（第一版只提供独立 SDK）
- 写明哪些相关问题会留到后续 request 处理
  - 工具调用完整实现 → 第二阶段 B
  - 生产级稳定性 → 第二阶段 C
  - SSE 支持 → 后续 request

## 风险

- 说明回归风险、兼容性风险、联调风险、数据风险
  - 新增项目，无回归风险
  - 后端 WebSocket 接口尚未实现，第一版用 mock
  - Vue 组件打包成 SDK 可能有体积问题，需要优化
- 若暂无显著风险，也要明确写“当前未识别到高风险运行时变更”

## 停点判断

- 是否涉及架构边界变化
  - 是（新增 SDK 项目）
- 是否涉及数据模型变化
  - 否
- 是否涉及 API 契约变化
  - 是（新增 SDK API）
- 是否涉及鉴权或权限行为变化
  - 是（SDK 鉴权设计）
- 若任一项为“是”，必须明确写“进入实现前需人工确认”
  - 进入实现前需人工确认

## 验收标准

- 用可检查、可验证的句子描述完成标准
  - ✅ `apps/ai-sdk` 目录结构完整，包含所有必要文件
  - ✅ `npm run build` 能正常输出 ESM 和 UMD 包
  - ✅ Demo 页面能正常运行，演示 createAgentClient、sendMessage、open/close UI 等功能
  - ✅ TypeScript 类型定义完整，无类型错误
  - ✅ 代码结构清晰，分层明确（core、ui）
- 尽量避免只写“功能正常”这类模糊描述
- 若是文档工程任务，也要写清要补齐哪些文档资产

## 变更记录

### 2026-07-31 第 2 次变更

- 变更原因：补充第三方接入方可直接执行的 SDK 使用说明。
- 变更内容：新增完整接入手册，覆盖 Embed Client、服务端 token 代理、浏览器初始化、无 UI 模式、宿主工具、本地 Demo 和安全检查。
- 影响章节：范围、验收标准。
- 是否触发人工确认：否，仅新增文档，不改变运行时行为、API 契约或鉴权语义。
- 关联计划更新：本次为文档补充，沿用已完成的 token 身份边界设计。

### 2026-07-31 第 1 次变更

- 变更原因：明确 SDK token 获取逻辑和 `external_user_id` 身份来源，避免生产接入将长期 secret 或未校验用户 ID 放入浏览器。
- 变更内容：`getToken` 接收 token provider context；补充短期 Embed Token、终端用户身份和 Demo/生产边界文档；增加 token provider 与重连行为测试。
- 影响章节：范围、风险、停点判断、验收标准。
- 是否触发人工确认：是，涉及鉴权和 API 契约；已于 2026-07-31 获得确认。
- 关联计划更新：同步更新本 request 的 `plan.md`。

## 增量设计：生产接入身份边界

### 目标

- 让 SDK 使用者明确 `getToken` 获取的是短期 Embed Access Token，而不是模型密钥或 `client_secret`。
- 让 `external_user_id` 的来源落在接入方服务端的登录态或匿名会话，而不是由 SDK 生成或由网关信任浏览器任意提交。
- 保持既有 WebSocket `auth` 消息、JWT claims 和数据库模型兼容。

### 方案

`AgentClientOptions.getToken` 改为接收 `TokenProviderContext`。SDK 在每次建立连接或重连认证时传入 `platformId`、`agentId` 和可选 `user`；token provider 决定如何调用接入方自己的后端接口。SDK 只把 provider 返回的短期 token 放到既有 `auth.payload.token`，不自行生成或补写 `external_user_id`。

生产推荐链路为：用户访问接入方页面 -> 页面调用接入方后端 token 代理 -> 代理从登录态取得 `external_user_id` 并用服务端 `client_secret` 请求 `POST /api/v1/embed/tokens` -> 页面得到短期 `access_token` -> SDK 通过 WebSocket `auth` 使用该 token。现有 `/api/agent-token?external_user_id=...` 仅作为本地 Demo 代理，文档明确其不可直接作为生产身份认证。

### 风险与停点

- 本次涉及 SDK token provider API 和鉴权接入约定，但不改变后端 token claims 或 WebSocket 协议；人工确认已完成。
- 接入方若仍让浏览器自行指定 Demo 接口的 `external_user_id`，仍可能冒用同平台其他终端用户；文档和测试只能明确边界，不能替接入方补齐其业务登录认证。
- token provider 返回空字符串时 SDK 必须拒绝认证并触发错误，避免发送无效 auth 帧。

### 增量验收标准

- `getToken` 类型和 README 示例明确说明返回短期 Embed Access Token。
- SDK 每次认证都向 provider 传递稳定上下文；重连会重新获取 token，不缓存过期 token。
- SDK 不生成、不拼接、不通过 WebSocket 发送 `external_user_id`。
- 空 token 被 SDK 拒绝，既有 token 发送和重连测试继续通过。
- 本地 Demo 和生产接入示例分别标注适用范围。

### 初始版本

- 时间：2026-07-24
- 变更原因：首次创建 request
- 变更内容：建立本次任务的初始设计说明
- 影响章节：全部
- 是否触发人工确认：是
