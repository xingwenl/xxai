---
id: 2026-09-20-ai-sdk-pc-sidebar-conversations
tier: B
risk: medium
approval:
  required: true
  granted: true
  why: ["API 契约变化（新增 Embed 会话列表与删除接口）", "鉴权/权限行为变化（新增按 embed token 主体枚举会话的权限面）"]
---

## 目标与范围

- 给 `xxai-agent` SDK 增加 **PC 端适配**：新增 `desktop` 布局 —— 宽屏下左侧常驻会话列表、右侧对话区，窄屏自动退化为单栏。
- 左侧列表点击可 **切换会话并加载历史消息**；另支持 **新建会话** 与 **删除会话**。
- 会话集合由后端按「平台 + Embed Client 最终用户 + Agent」隔离下发，SDK 不再只依赖本地单会话缓存。
- **删除为软删除**：只把会话标记为 `status='deleted'`，从列表与后续解析中排除；消息、附件与用量记录一律保留。
- 目标用户：在 PC 页面（`apps/shop`、桌面壳渲染层）接入 SDK 的接入方，以及需要在多轮对话间切换的终端用户。
- 完成后可验证结果：`ui.mode: 'embedded'` 配新布局时 PC 宽屏出现左侧列表并可点击进入历史会话；窄屏与既有 `floating` 行为逐条不变。

## 来源与方案比较

- 本机源码 Pi（`/Users/lixingwen/xw/git/pi`，commit `4e69b0c28`，2026-09-02）：`packages/protocol/src/schemas.ts` 用 `SessionMetadata{id, createdAt, updatedAt, sessionName}` 作列表轻量投影；`packages/server/src/sessions.ts` 的 `list` 只回元数据、正文经独立 `attach` 取快照。结论：**列表与正文分离、列表项只含可排序元数据**是成熟做法。
- 本仓库既有实现：`GET /embed/conversations/{id}/messages`（消息快照）与 `/embed/conversations/{id}/assets/{asset_id}`（受保护附件）已存在，SDK 的 `client.loadAsset()` 已能把历史 `asset_id` 换成 Blob URL。结论：历史渲染链路可复用，不重造。
- 方案 A（采用）：新增 `GET /embed/conversations` 列表接口 + `desktop` 布局模式 + 软删除。
- 方案 B（否决）：物理删除会话。理由见「被否决的选项」与「风险」。
- 方案 C（否决）：复用 WebSocket 新增 `conversation_list` 事件。理由见「被否决的选项」。

## 被否决的选项

- **物理删除会话（级联删消息与附件）**：`model_usage_records.conversation_id` 是 `ondelete="CASCADE"`（`app/modules/conversation/models.py`），物理删除会连带销毁 token 用量与计费记录，而这些记录是后台用量报表（`/platforms/{id}/model-usage`、按会话汇总）的事实来源，且不可恢复；同表的 `host_tool_audit` / `task_run` / `skill_invocation` 却用 `SET NULL` 保留审计。要改成保留用量需动 `models.py` + 迁移，升为 A 档并新增 ADR，收益不抵成本。用户已确认改用软删除。
- **WebSocket 新增 `conversation_list` 协议事件**：列表是带分页/排序的只读查询，走 WS 需新增请求-响应关联与超时语义，与现有只含广播语义的 `envelope()` 冲突，还会牵动 `gateway/auth.py` 的 `CAPABILITIES` 与 `check_client_compatibility` 版本协商。HTTP 侧已有 `get_current_embed_claims` 可复用，成本更低。
- **仅本地多会话（localStorage 多 key）**：会话事实来源在数据库，本地多 key 在换设备、清缓存、多标签页下与后端不一致，也无法满足「加载历史消息」的真实诉求。
- **列表项直接返回完整消息数组**：按 Pi 的元数据投影做法，列表与正文分离，避免 N×全量消息的响应膨胀与慢查询。
- **删除时 unlink 磁盘附件文件**：软删除下附件行与文件都必须保留（否则「已删除」会话的历史附件在别处引用时会 404），且物理清理属数据合规策略（Phase 2C 未决项）。

## 停点判断

- 是否涉及架构边界变化：否（embed 模块内新增路由；SDK 内新增布局分支）。
- 是否涉及数据模型变化：否（复用既有 `Conversation.status` 字段，不加列、不写迁移）。
- 是否涉及 API 契约变化：**是**（新增 `GET /api/v1/embed/conversations`、`DELETE /api/v1/embed/conversations/{id}`）。
- 是否涉及鉴权或权限行为变化：**是**（新增「embed token 主体可枚举/软删除自己的会话」权限面）。
- 命中两项 → `approval.required: true`，实现前须获人工确认。

## 变更点

- `apps/backend/app/modules/embed/schemas.py`：新增 `EmbedConversationRead`（`id`/`title`/`created_at`/`message_count`/`last_message_preview`）与 `EmbedConversationPage`（`items`/`total`/`page`/`page_size`）。
- `apps/backend/app/modules/conversation/repositories.py`：新增 `list_for_principal(platform_id, agent_id, *, end_user_id, page, page_size)`、`count_for_principal(...)`、`soft_delete_for_principal(conversation_id, platform_id, *, end_user_id)`；`get_for_principal` 增加 `status != 'deleted'` 过滤，使软删除会话不可被重新解析（连带影响 REST/SSE 与网关两条解析路径，属预期一致化）。
- `apps/backend/app/modules/embed/services.py`：新增 `list_embed_conversations` 与 `soft_delete_embed_conversation`，把 claims 拆成 `platform_id`/`sub`/`agent_id` 后交给仓储；服务层不拼 SQL。
- `apps/backend/app/modules/embed/router.py`：新增两个端点，沿用 `get_current_embed_claims` 与 `success_response`；`agent_id` 取自 token claim，不接受查询参数覆盖；列表按 `created_at` 倒序。
- `apps/ai-sdk/src/core/types.ts`：新增 `ConversationSummary`、`UIOptions.layout?: 'single' | 'desktop'`、`UIOptions.sidebar?: { width?: number }`，全部可选，缺省即现状。
- `apps/ai-sdk/src/core/client.ts`：新增 `listConversations()`、`openConversation(id)`、`startNewConversation()`、`deleteConversation(id)` 与 `conversations_changed` 事件；`openConversation` 需原子重置 `MessageStore`、`pendingAssistantMessage`、`pendingLoop`、canonical `conversationId` 与 WS 游标 `_lastSequence` 后再拉快照。
- `apps/ai-sdk/src/ui/components/ConversationSidebar.vue`（新文件）：列表渲染、当前项高亮、新建/删除入口；只做展示与事件上抛，不直接调 HTTP。
- `apps/ai-sdk/src/ui/components/ChatWidget.vue`、`src/ui/index.ts`、`src/ui/styles/index.css`：新增 `desktop` 双栏容器与 `< 768px` 单栏降级（抽屉式列表）。
- `apps/ai-sdk/README.md`：新增「PC 双栏与会话列表」章节，写明删除为软删除、数据不销毁；`docs/CHANGELOG.md` 记录。
- 验证方式：SDK 跑 `type-check`/`test -- --run`/`build`+`verify-package`；后端跑 `pytest tests/embed tests/conversation tests/gateway -q` 与 `ruff check`；新增 SDK 单测覆盖切换会话的状态重置，后端单测覆盖跨主体越权返回 404 与软删除后不可解析。

## 验收标准

- `GET /embed/conversations` 只返回「同平台 + 同 token 主体 + 同 Agent + `status='active'`」的会话，按 `created_at` 倒序分页；换另一主体 token 请求，结果不含前者任何会话。
- `DELETE /embed/conversations/{id}` 对非本主体会话返回 404（与既有快照接口一致，不泄露存在性）；对本人会话置 `status='deleted'`，此后列表不再返回该项，且 `conversation_messages`、`conversation_assets` 与 `model_usage_records` 行数与磁盘文件均不变。
- 软删除后再以该 `conversationId` 发消息，解析失败且不复活该会话（`get_for_principal` 过滤生效）。
- SDK：`layout: 'desktop'` 时，**悬浮与嵌入式两种模式**在面板够宽时都渲染左列表 + 右对话区（断点按面板自身宽度判断，非浏览器视口）；`floating` 默认宽 430px 因此默认走抽屉形态，拉宽到 900px 后列表常驻。点击列表项后消息区被该会话历史整体替换，`agent.getMessages()` 与新会话一致，后续消息落入该 `conversationId`。
- SDK：新建会话清空消息区并解绑旧 `conversationId`；删除当前会话后回落到新建态或列表首项，不出现空白卡死。
- SDK：`layout` 缺省、以及既有 `floating` / `embedded` 单栏路径的 DOM 结构、拖拽缩放与移动端媒体查询与改动前一致。
- 历史消息中的附件（`contentBlocks` 内 `asset_id`）经 `loadAsset()` 正常渲染，仍受既有鉴权接口保护。

## 风险

- 权限风险：新增「按主体枚举会话」能力，任何 `end_user_id` 过滤缺失都会横向泄露他人会话；缓解方式是与 `list_messages_for_principal` 复用同一 `get_for_principal` 口径，并用跨主体测试兜底。
- 语义风险：`get_for_principal` 加 `status` 过滤会同时改变 REST/SSE 与网关路径对「已软删除会话」的行为（从可用变为 404）；这是本次刻意的一致化，但需确认无既存调用方依赖「软删除会话仍可续聊」。
- 状态风险：`openConversation` 要同时重置 `MessageStore`、`pendingAssistantMessage`、`pendingLoop`、canonical `conversationId` 与 WS 游标 `_lastSequence`；漏重置任一会出现「历史消息 + 上一条流式回答」串台，是本 request 最高回归风险点。
- 数据风险：无迁移、无物理删除，回滚只需把 `status` 改回 `active`；代价是软删除会话的消息与附件长期占用存储，需在 README 说明并由后续数据保留策略处理。
- 兼容风险：`layout` 为新增可选字段，旧接入方不传即保持单栏，`0.1.x` 消费者不受影响。

## 变更记录

### 修正：布局适用范围与断点口径（2026-09-20）

- 变更原因：首版把 `layout: 'desktop'` 描述为「仅嵌入式生效」，实际实现按 `props.layout` 判断、与模式无关；用户指出 floating 同样有效后经浏览器实测确认。
- 修正内容：断点改按**聊天面板自身宽度**判断（原先用 `window.innerWidth`）。原口径下 430px 悬浮窗停在宽视口时不会降级，260px 常驻列表会把对话区挤到 170px；现悬浮窗宽度即断点依据，拖拽缩放后重新判断。
- 连带修复：面板在 `isOpen` 生效后才挂载，观察器改为每次面板出现（`open()` / `ui_toggle` / `onMounted`）时重新 attach，否则嵌入式窄容器也不降级。
- 影响章节：验收标准、变更点、`UIOptions.layout` JSDoc、README「PC 双栏与会话列表」。
