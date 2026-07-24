# 业界调研记录

## 调研问题

- 本次要解决什么问题？
  - 创建一个 AI Agent JS SDK，允许第三方网站快速嵌入 AI 聊天功能，并支持工具调用
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - SDK 的整体架构设计
  - 类型系统设计
  - 传输层选择（WebSocket vs SSE）
  - UI 框架选择
  - 打包配置

## 功能复杂度

- 级别：核心功能
- 选择理由：这是一个完整的 SDK 项目，包含通信层、状态管理、UI 层等多个模块
- 最低调研要求：至少参考 1-2 个成熟开源项目

## 参考依据

### 来源 1

- 类型：成熟开源项目
- 名称：agentpage
- 链接：https://www.npmjs.com/package/agentpage
- 版本或发布日期：1.0.0（4 months ago）
- 调研日期：2026-07-24
- 核心做法：
  - core/web 分层架构，core 零 DOM 依赖
  - 完整的回调系统（onRound、onToolCall、onText、onMetrics 等）
  - TypeBox 做工具参数的运行时类型校验
  - Agent Loop 编排、工具注册分发
  - 支持内置工具和自定义工具
  - 完整的 metrics 指标收集
- 对本项目的启发：
  - 分层架构很重要，保持 core 纯 TypeScript
  - 完善的回调系统提升用户体验
  - 类型安全的工具定义是必要的
  - 连接状态管理和重连机制

### 来源 2

- 类型：官方设计文档
- 名称：agent-js-sdk-integration-brief.md
- 链接：.worktrees/configurable-agent-platform/docs/design/agent-js-sdk-integration-brief.md
- 版本或发布日期：2026-07-24
- 调研日期：2026-07-24
- 核心做法：
  - 推荐 headless + floating UI 模式
  - WebSocket 协议设计（消息信封、事件类型）
  - 鉴权方案：短期 embed token
  - 宿主工具规范（JSON Schema、副作用等级）
- 对本项目的启发：
  - 协议设计已经很详细，按这个实现
  - 先做第二阶段 A，后续再加工具
  - 架构要支持后续扩展

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：双打包（核心+UI 层合一） | 架构清晰，易于扩展，单一入口简单 | 需要处理 Vue 打包到 SDK 的问题 | 高 |
| 方案 B：三层分离（核心包+UI 包独立） | 最灵活，用户按需选择 | 维护成本高，第一版太复杂 | 中 |

## 最终决策

- 选择方案：方案 A（双打包，核心+UI 层合一）
- 选择原因：
  - 第一版需要简单直接，单一入口对用户友好
  - 架构保持分层，未来仍可拆分为独立包
  - 符合设计文档的分期策略
- 不选择其他方案的原因：
  - 方案 B 过度设计，第一版不需要如此复杂
- 对后续 spec、plan 或人工确认的影响：
  - 明确使用 TypeScript + Vue 3 + Vite
  - 明确传输层优先 WebSocket，预留 SSE 接口

## 剩余风险

- 资料时效性：agentpage 是 4 个月前发布的，比较新
- 与本项目上下文的差异：agentpage 是浏览器原生 Agent，我们是连接后端的 SDK
- 尚未验证的假设：Vue 组件打包成 SDK 的最佳实践需要进一步验证
