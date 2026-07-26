# Phase 2A AI Agent SDK WebSocket 启动交接

## 1. 给新窗口的第一条指令

在新窗口中直接发送：

```text
请继续 request 2026-07-26-agent-sdk-websocket-foundation。
先读取根目录 AGENTS.md、docs/design/agent-sdk-phase-2-requirements.md、该 request 下全部文件，以及 docs/handoff/phase-2-agent-sdk-websocket-foundation.md。
检查 meta.json 的 approvalGranted；未确认时先提交方案确认，不得实现。确认后使用永久 worktree，严格按 plan.md Task 0 -> Task 9、TDD 和 checkpoint 顺序执行。
```

## 2. 当前仓库状态

- 根仓库：`/Users/lixingwen/xw/study/ai-base`
- 第一阶段已合并到 `main`。
- 第一阶段合并提交：`2e90ea3 Merge branch 'codex/configurable-agent-platform-rebuild'`。
- 第一阶段永久 worktree：`.worktrees/configurable-agent-platform`，按用户要求保留用于追溯。
- 当前后端全量基线：`89 passed`，Ruff 通过。
- 当前 SDK type-check/build 通过，TypeScript 固定为 `5.4.2` 以兼容 `vue-tsc 1.8.27`。

开始 Phase 2A 前，新窗口必须重新执行 `git status --short --branch` 和基线测试，不应假设工作区仍与本文完全一致。

## 3. 必读文件

1. `AGENTS.md`
2. `docs/harness/policies/global.md`
3. `docs/design/agent-sdk-phase-2-requirements.md`
4. `docs/design/agent-js-sdk-integration-brief.md`
5. `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/research.md`
6. `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/spec.md`
7. `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/plan.md`
8. `docs/harness/requests/2026-07-26-agent-sdk-websocket-foundation/meta.json`
9. `apps/backend/app/modules/conversation/`
10. `apps/ai-sdk/src/core/` 和 `apps/ai-sdk/src/ui/`

## 4. 已确认事实

- 后端已有 LangGraph Conversation Runtime、知识库引用和 MCP 事件，不应重写 Agent 核心。
- 后端目前没有 WebSocket、Embed Client、平台最终用户和 token exchange。
- SDK 的 WebSocket 是 Mock，SSE 是占位；现有 UI 只是可复用骨架，不是已完成产品。
- SDK 当前 `text_delta` 与后端 `message_delta` 不一致，Phase 2A 统一为 `message_delta`。
- 浏览器 WebSocket 不能设置任意 Authorization header，token 不得放 URL；连接后使用 auth 事件。
- PostgreSQL 保存长期业务事实，Redis Streams 只保存 15 分钟可重放事件和有期限状态。
- Phase 2A 不实现宿主工具。宿主工具完整需求已写入总纲，后续单独创建 Phase 2B request。

## 5. 当前人工确认点

`meta.json` 当前为：

```text
phase=plan
status=active
approvalRequired=true
approvalGranted=false
```

进入实现前必须让用户一次性确认以下五项：

1. 原生 WebSocket + `ai-agent.v1`，不使用 Socket.IO。
2. Embed Client 服务端 secret 换 5 至 15 分钟 token，token 不进 URL。
3. 新增 PlatformEndUser，Conversation 支持内部和外部两类主体。
4. Redis Streams 保存 15 分钟、最多 1000 条事件用于短断线恢复。
5. 本 request 只做 Phase 2A，宿主工具进入后续 Phase 2B。

用户确认后，先更新 `approvalRecords` 和 `approvalGranted`，提交文档 checkpoint，再进入 Task 1。

## 6. 工作方式

- 必须创建根仓库下的永久 worktree，不使用 `/tmp`。
- 推荐分支：`codex/agent-sdk-websocket-foundation`。
- 每个 Task 使用 TDD：先写失败测试并确认失败原因，再实现最小代码。
- 每个 Task 定向验证通过后创建 checkpoint。
- 不修改与当前 Task 无关的历史 Black 格式问题。
- 遇到 API、数据模型或鉴权方案变化，回到 spec 记录增量并重新确认。
- 新窗口的实现进度写回 plan checkbox、verify 和 meta，不依赖聊天消息作为唯一记录。

## 7. 推荐的第一个实现动作

人工确认并创建永久 worktree 后，从 Task 1 开始：先建立后端/SDK 共用协议 fixture 与自动化测试，固定 `ai-agent.v1` 信封和错误模型。不要先写 WebSocket endpoint，也不要先改 UI。

## 8. 验收和合并

完成 Task 9 前不得声称 request done。最终必须有：

- 真实 PostgreSQL/Redis 迁移和联调证据；
- 后端全量测试和静态检查；
- SDK test/type-check/build；
- 浏览器流式、引用、取消、重连、token 过期和 destroy 证据；
- 跨平台、Origin、audience、Agent、主体和 jti 拒绝测试；
- 更新后的 verify、acceptance、meta 和 Changelog；
- 最终 checkpoint 以及合并后复测。
