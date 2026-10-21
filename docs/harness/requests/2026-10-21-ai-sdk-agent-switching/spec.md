---
id: 2026-10-21-ai-sdk-agent-switching
tier: A
risk: medium
approval:
  required: true
  granted: true
  why: ["数据模型变化：PlatformEmbedClient 新增 allow_agent_switching 列 + migration", "API 契约变化：session_ready 的 client 快照新增 allowAgentSwitching、GET /embed/agent-token 新增可选 agent_id、SDK 公开选项新增 agentSwitching", "跨 apps/ 改动：apps/backend + apps/ai-sdk + apps/front"]
---

## 目标与范围

一句话：让 ai-sdk 聊天窗的表头可以选择「后台已配置的智能体」，并且这个能力由**后台 embed client 的一个开关**统一控制开启/关闭；关闭时 SDK 既不显示入口，程序化切换也直接拒绝。

具体交互：用户点表头当前智能体名称 → 下拉列出宿主传入的可用智能体（名称 + 描述，当前项打勾）→ 选中另一个 → SDK 先为目标 agent 换 token，成功后才断开重连，并按该 agent 的本地存储恢复它上次的会话；失败则留在原 agent，什么都不改。

**不做**：

- 不新增「SDK 拿着 embed token 去后端拉候选列表」的公开接口；候选列表由宿主（接入方）提供，后端只做绑定校验。
- 不同步改造 `apps/desktop`、`apps/shop` 的接入；它们的 `agentSwitching` 保持关闭，行为不变。
- 不支持跨 client 切换（token 绑定单一 client，这是既有安全边界）。
- 不做会话历史跨 agent 迁移；不做 WS 协议、token claim、网关鉴权规则改动。

## 来源与方案比较

- 仓库内既有先例：`session_ready` 已下发 client/agent/quota 快照（`apps/backend/app/modules/gateway/router.py:836-850`），token 里已有 `agent_id` 且网关强校验「token.agent_id == 路径 agent_id」（`apps/backend/app/modules/gateway/auth.py:77-100`）——所以切换必须是「换 token + 换 WS 路径」，这是既定约束而不是本次选择。
- Open WebUI（开源，当前主线版本，访问日期 2026-10-21）：模型/智能体选择器由**后端**提供列表，选择结果按会话持久化——https://docs.openwebui.com/
- LibreChat（开源，当前主线版本，访问日期 2026-10-21）：Agents 列表由后端 `/api/agents` 提供，前端只做选择与切换——https://docs.librechat.ai/
- 结论：业界做法是「列表权威方提供列表，前端只做选择」。本仓库的特殊性在于**列表权威方是后台管理员配置、而 SDK 运行在第三方宿主页面**，因此候选列表的搬运责任落在宿主，而不是新增一个对外接口。

| 方案 | 做法 | 结论 |
|---|---|---|
| A 后端新增公开接口 | 携 embed token 调 `GET /embed/agents` 返回绑定 agent（含名称/描述） | 列表最权威；但新增对外鉴权面、SDK 与后端版本耦合，且绑定关系只在平台侧可配 |
| B 宿主静态列表（采纳） | 宿主自己取列表并 `agentSwitching.agents` 传入，SDK 负责 UI 与切换；后端仍校验绑定 | 零新增对外契约；越权由服务端 401 兜底；宿主多写 10 行 |
| C 只给程序化接口不做 UI | SDK 只暴露 `switchAgent`，宿主自绘 | 违背「在 ai-sdk 里可以选」的原始诉求 |

## 被否决的选项

- **后端新增公开候选列表接口（方案 A）**：多一个对外鉴权面与版本耦合面；而 SDK 侧静态列表 + 服务端绑定校验已能 fail closed（未绑定的 agent 换 token 直接被拒），净收益不足。
- **把开关做成 SDK 配置项（`agentSwitching.enabled`）**：开关表达的是**平台策略**，同一 client 的多个宿主应行为一致；放 SDK 里管理员无法统一关闭，等于没开关。
- **用 token claim 下发开关**：token 最长 900s 生命周期且客户端会按 exp 缓存复用，管理员改配置后存在最长 15 分钟的旧策略窗口；`session_ready` 快照随连接刷新，语义更准。
- **切换时新建空会话**：用户切回原 agent 会丢掉刚才的上下文；而本地存储本来就按 agent 隔离，「恢复该 agent 上次会话」是零成本语义。
- **切换时把当前会话历史带进新 agent**：两 agent 的模型/系统提示/工具集不同，历史迁移污染上下文；后端会话也按 agent_id 隔离，技术上无法续用。
- **直接复用后台管理接口给 SDK**：SDK 是公开包，不能假设宿主具备后台管理员登录态；且 `PlatformEmbedClientAgentRead` 只有 `{id, client_id, agent_id}`，渲染不出名称。
- **在忙碌时排队切换**：生成中重建 transport 会丢事件与 token 流，行为不可预期；直接禁用并说明原因更诚实。

## 停点判断

- 是否涉及架构边界变化：否（沿用 embed client 配置 → 网关快照 → SDK 客户端这条既有链路）
- 是否涉及数据模型变化：是（`PlatformEmbedClient` 新增布尔列 `allow_agent_switching` + migration）
- 是否涉及 API 契约变化：是（`session_ready` client 快照、`GET /embed/agent-token` 查询参数、SDK 公开 `AgentClientOptions`）
- 是否涉及鉴权或权限行为变化：否（不新增主体/角色；agent-token 仍要求后台登录态，显式 `agent_id` 走既有 `is_agent_allowed` 校验）
- 结论：A 档，`approval.required: true`；本文件写完后先确认要点，再写实现代码。

## 变更点

后端：

- `apps/backend/app/modules/embed/models.py`：`PlatformEmbedClient` 新增 `allow_agent_switching`（Boolean、非空、默认 False、中文 comment）。
- `apps/backend/migrations/versions/20261021_0044_embed_client_agent_switching.py`：`add_column` + `server_default=false`（存量 client 默认关闭），docstring 指向 ADR 0014。
- `apps/backend/app/modules/embed/schemas.py`：Create/Update/Read 三处补字段（Create 默认 False，Update 可选）。
- `apps/backend/app/modules/embed/services.py`：`create_embed_client` 透传新字段（Update 走既有 `exclude_unset`）。
- `apps/backend/app/modules/gateway/router.py:836-843`：client 快照新增 `allowAgentSwitching`。
- `apps/backend/app/modules/embed/router.py:185-204`：`GET /embed/agent-token` 新增可选 `agent_id` 查询参数并透传给 `issue_configured_agent_token`。
- `apps/backend/tests/embed/{test_client_services,test_token_routes}.py`、`apps/backend/tests/gateway/`：覆盖默认关闭、PATCH 开关、快照字段、`agent_id` 透传与未绑定拒绝。

SDK：

- `apps/ai-sdk/src/core/types.ts`：新增 `AgentSwitchOption`、`AgentSwitchingOptions`、`AgentClientOptions.agentSwitching?`、`EmbedClientInfo.allowAgentSwitching?`、`agent_switched` 系列事件类型。
- `apps/ai-sdk/src/core/agent-switching.ts`（新）：`shouldShowAgentSwitcher`、`deriveAgentEndpoint`、`buildSelectionStorageKey`、`formatAgentSwitchError` 等纯函数。
- `apps/ai-sdk/src/core/client.ts`：`storageKey` 改为按 active agent 派生的 getter；新增 `availableAgents`/`canSwitchAgent`/`isSwitching`；`switchAgent(agentId)` 两阶段（预签 token → 重建 transport → 恢复该 agent 本地会话），失败不改现状；选中项持久化，`allowAgentSwitching=false` 时回退默认 agent 并清记忆；重建后用 `toolRegistry.getTools()` 重注册工具、清 pending 确认/提问。
- `apps/ai-sdk/src/ui/components/AgentSwitcher.vue`（新）与 `ChatWidget.vue`：表头下拉、当前项打勾、忙碌禁用、失败轻提示；订阅 `agent_switched` 刷新标题/头像/会话列表。
- `apps/ai-sdk/src/ui/styles/index.css`：选择器样式（沿用既有 token 与暗色方案）。
- `apps/ai-sdk/src/core/__tests__/agent-switching.test.ts`（新）+ `client.test.ts` 补用例；`apps/ai-sdk/README.md` 新增「智能体切换」小节。

接入与文档：

- `apps/front/src/features/agent-navigation/agent-navigation-bridge.tsx`：读 `VITE_AGENT_CLIENT_ID`，用后台登录态取启用 agent 与绑定的交集传给 `agentSwitching`，`requestAgentToken` 带 `agent_id`；缺 CLIENT_ID 时不启用并 `console.warn`。
- `apps/front/src/features/embed-clients/{index.tsx,api}`：表单开关与列表徽标、类型补字段。
- `CONTEXT.md` 术语（智能体切换 / 可用智能体 / 智能体切换开关）、`docs/adr/0014-host-provided-agent-switching.md`、`docs/CHANGELOG.md`。
- 新增 `tools/harness/verify/2026-10-21-ai-sdk-agent-switching.sh` 与其产出的 `verify.md`。

## 验收标准

1. 后端 `pytest`（embed + gateway 相关）通过，且断言：新建 client `allow_agent_switching=false`、PATCH 可开、`session_ready` 快照含 `allowAgentSwitching`、`/embed/agent-token?agent_id=` 透传且未绑定返回 4xx。
2. `alembic upgrade head` 通过；migration 的 `downgrade` 能删列回退。
3. `pnpm --filter xxai-agent run type-check` 与 `pnpm --filter xxai-agent exec vitest run` 通过；新增用例覆盖：预签失败不改状态、成功切换后工具重注册、按 agent 恢复本地会话、记住/清除选中项、开关关闭时不显示且回退、忙碌拒绝。
4. `pnpm --filter xxai-agent run build` 成功，产物含切换器且未新增运行时依赖。
5. `pnpm --filter front exec tsc --noEmit` 通过；缺 `VITE_AGENT_CLIENT_ID` 时不传 `agentSwitching` 且 `console.warn`。
6. `apps/ai-sdk/README.md` 出现「智能体切换」小节，写明宿主传列表 + 后台开关 + fail closed 三条约束。
7. `python3 tools/harness/audit.py` 无本次新增 ERROR。

未执行项：真实后端 + 真实模型下「切到另一个 agent 并成功对话」的端到端验证（依赖本机后端与模型可用），由 verify 脚本显式列出。
