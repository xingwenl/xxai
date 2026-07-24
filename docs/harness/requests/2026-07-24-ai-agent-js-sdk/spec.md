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

### 初始版本

- 时间：2026-07-24
- 变更原因：首次创建 request
- 变更内容：建立本次任务的初始设计说明
- 影响章节：全部
- 是否触发人工确认：是
