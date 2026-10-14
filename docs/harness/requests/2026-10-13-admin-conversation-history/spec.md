---
id: 2026-10-13-admin-conversation-history
tier: A
risk: medium
approval:
  required: true
  granted: true
  why: ["API 契约变化：新增 /platforms/{platform_id}/conversation-principals 与 /conversations 系列路由", "权限行为变化：平台管理员将可读取本平台全部会话（含终端用户与其它后台用户发起）的完整消息正文", "架构边界变化：改动已发布库 xxai-agent 的公开导出与其构建产物契约"]
  grantedAt: 2026-10-13
  grantedBy: 用户（拷问收尾轮 + 方案要点确认：「确认 开始吧」）
---

## 目标与范围

一句话：给后台管理加「会话记录」只读视图，按**会话主体 → 会话列表 → 会话内容**三层展示平台内的全部会话，并用 ai-sdk 现有渲染展示消息与 Agent 过程。

- 使用者：平台管理员。可见范围＝本平台的全部会话（`conversations.platform_id` 同平台），含后台用户发起的与终端用户（embed）发起的。
- 数据来源：`conversations` / `conversation_messages` / `agent_loop_runs` / `agent_loop_steps` / `model_usage_records`（全部已落库），不新增表、不加列、不加索引。
- 复用 ai-sdk：新增两个可嵌组件 `ConversationList`、`ConversationHistory`，第三层消息与 Agent 过程复用库内既有 `ChatMessage.vue` / `AgentLoopPanel.vue` / `MarkdownContent.vue`。
- `/chats` 现有 IM 页面原样保留（它的 `/api/chat/*` 后端不在本仓库，本次不处理）。

**不做**（非目标）：

- 不新增数据库表/列/索引，不做 Alembic 迁移。
- 不做消息正文全文检索；关键字只匹配会话 `title` 与末条消息摘要。
- 不做会话重命名、导出、接管对话、以管理员身份继续发消息。
- 不做跨平台全局视图（那要先有全局管理员角色，属鉴权模型变化）。
- 不在 ai-sdk 内实现任何 HTTP 调用与鉴权。
- 不动 ai-sdk 既有导出、既有 `dist/style.css` 文件名与既有组件行为。

## 来源与方案比较

- **消息与 Agent 过程的投影直接复用 embed 侧已实现并已验证的形状**：`ConversationMessageRead`（`apps/backend/app/modules/embed/schemas.py:87-101`）的 `loop` 字段形状与 ai-sdk 的 `Message.loop`（`apps/ai-sdk/src/core/types.ts:90-95`）一致，且 `apps/ai-sdk/src/core/client.ts:906-946` 已在消费它 ⇒ 后台接口逐字复用该投影，SDK 侧零适配。
- **列表形状沿用既有做法**：`EmbedConversationPage(items/total/page/page_size)` 与 `ConversationRepository.list_for_principal`（`apps/backend/app/modules/conversation/repositories.py:77-119`）的两条相关子查询（消息数 + 末条消息摘要），已解决「列表只回元数据、正文走独立接口」的分页问题。
- **后台面路由与守卫照抄既有模块**：`apps/backend/app/modules/model_usage/router.py:17-63`（`prefix=/platforms/{platform_id}/...` + 分页 Query + `_require_admin` + `success_response`）。
- **三层结构的既有先例**：`tasks`（列表 `apps/front/src/features/tasks/index.tsx` + 独立详情 `apps/front/src/features/tasks/task-detail-page.tsx`）与 `workflows`，路由文件与 feature 分离。

## 被否决的选项

- **把 ai-sdk 的 Vue 聊天岛整块嵌进后台**：ai-sdk 只打 embed-claims 作用域接口（平台/终端用户/Agent 全取自 embed token），管理员 token 打不通；要接通只能伪造 embed token，等于让后台复用「以终端用户身份发请求」这条路径，是权限模型的实质变更。其浮窗按钮还是 `position:fixed; z-index:9999`，与后台浮窗会打架。
- **让 SDK 自带 HTTP 实现**：会让已发布库获得「后台接口路径与平台隔离」这类知识，与仓库「`src/api/` 统一封装后端接口」的边界冲突，且宿主换鉴权方式就要发 SDK 版本。改为 SDK 只定义 `ConversationHistorySource` 接口，apps/front 在 `src/api/` 实现。
- **为 ai-sdk 增加子路径导出（`xxai-agent/history` + `history.css`）**：lib 模式下 `cssCodeSplit` 默认 false，要拆出独立 CSS 就得打开它，可能导致既有 `dist/style.css` 改名，而 apps/front 等宿主依赖 `xxai-agent/style.css`——正是「影响 ai-sdk 以前的功能」。改为在主入口**追加导出**，新样式用 `xxai-history-*` 前缀并入现有单一样式文件。
- **给 `conversations` 加 `message_count`、`last_message_at` 冗余列**：属数据模型变化，且要与三条写入路径（`execute_chat`、`stream_chat`、gateway 落库）保持同步，回归面远大于收益。
- **第一层直接平铺全部会话**：会话量级随终端用户增长，一屏混排「谁跟谁的对话」不可读；用户已定三层结构。
- **`/api/admin/conversations` 这类全局前缀**：本仓库所有后台面都嵌在 `/platforms/{platform_id}/...`，平台隔离靠 `PlatformRepository.get_by_id_for_user` 返回 404 实现；新开全局前缀等于另起一套鉴权约定。
- **物理删除会话**：`model_usage_records.conversation_id` 是 `ondelete=CASCADE`，物理删除会连带销毁计费数据；沿用 embed 的软删除（`status='deleted'`）。

## 停点判断

- 是否涉及架构边界变化：**是**（改动已发布库 `xxai-agent` 的公开导出契约；新增前端 feature 目录）。
- 是否涉及数据模型变化：**否**（不新增表、列、索引，无迁移）。
- 是否涉及 API 契约变化：**是**（新增后台会话读接口族）。
- 是否涉及鉴权或权限行为变化：**是**（平台管理员首次可读取本平台终端用户与其它后台用户的会话正文）。
- 核心功能是否缺少关键资料：**否**（embed 投影、ai-sdk 消费端、既有后台列表范式均已在本仓库就地确认）。

四项命中，`approval.required: true`，进入实现前必须获得人工确认。ADR 见 `docs/adr/0003-conversation-history-read-boundary.md`。

## 变更点

**后端 `apps/backend/app/modules/conversation/`**

- 新增 `serializers.py`：把原先内联在 `get_embed_message_snapshot` 里的消息 + Loop 投影抽成 `build_message_snapshots(repo, *, conversation_id, messages)`（含 `build_loop_payload`、`conversation_preview`），embed 与后台两个入口共用同一份，输出形状与改动前逐字一致；不 import `conversation/services.py`（那条链带 langchain/agent_runtime 重依赖）。
- 新增 `admin_router.py`：`APIRouter(prefix="/platforms/{platform_id}", tags=["conversation-admin"])`；守卫沿用 `PlatformRepository.get_by_id_for_user`，非管理员 404；返回 `success_response`；在 `apps/backend/app/__init__.py` 登记。
  - `GET /conversation-principals`：主体聚合（`principal_type` ∈ `user|end_user`，只列有会话的主体），返回 `{principal_type, principal_id, display_name, conversation_count, last_conversation_at}` + 分页；名称取后台用户 `sys_users.name`、终端用户 `display_name` 回退 `external_user_id`。
  - `GET /conversations`：筛选 `principal_type`+`principal_id`、`agent_id`、`start_date`/`end_date`、`status`（默认排除 `deleted`）、`keyword`（`title` 或末条消息摘要），返回会话头 + `message_count`/`last_message_preview`/`last_message_at`/`agent_name`/主体显示名。
  - `GET /conversations/{id}`：会话头 + 主体 + Agent + 消息数 + 会话级用量汇总（`model_usage_records` 按 `conversation_id` 求和）。
  - `GET /conversations/{id}/messages`：调 `build_message_snapshots`，形状 ≡ embed 同接口。
  - `DELETE /conversations/{id}`：软删除 `status='deleted'`。
- `schemas.py` 新增 `ConversationPrincipalRead`、`ConversationPrincipalPage`、`ConsoleConversationRead`、`ConsoleConversationPage`、`ConsoleConversationDetail`；消息复用既有 `ConversationMessageRead`。
- `repositories.py`：`ConversationRepository` 增加 `list_principals_for_platform` / `count_principals_for_platform` / `list_for_platform` / `count_for_platform` / `get_for_platform` / `soft_delete_for_platform`；沿用既有相关子查询写法，主体显示名批量查，不做 N+1。
- `services.py`：新增 `list_console_conversation_principals` / `list_console_conversations` / `get_console_conversation` / `list_console_conversation_messages` / `soft_delete_console_conversation`。
- `apps/backend/app/modules/embed/services.py`：`get_embed_message_snapshot` 改为调用共用投影函数（对外行为不变）。

**ai-sdk `apps/ai-sdk/`**

- 新增 `src/history/types.ts`：`ConversationHistorySource`（`listConversations` / `listMessages`，返回后端原生 payload）、`ConversationSummaryPayload`、`ConversationMessagePayload`、`ConversationPagePayload`、`ConversationListParams`、loop 相关 payload 类型。
- 新增 `src/history/map-history.ts`：从 `src/core/client.ts` 的 `fetchHistory` 抽出「后端 payload → SDK `Message`」的映射（`mapHistoryMessage` / `mapHistoryMessages`），`client.ts` 与 history 共用一份。
- 新增 `src/history/ConversationList.vue`：会话列表（props: `source`、`params?`、`emptyText?`；emit `select`）。
- 新增 `src/history/ConversationHistory.vue`：消息时间线（props: `source`、`conversationId`、`showAgentLoop?`、`emptyText?`），复用 `ChatMessage.vue` + `AgentLoopPanel.vue`。
- 新增 `src/history/index.ts` 并在 `src/index.ts` **追加** `export { ConversationList, ConversationHistory } from './history'` 与相关类型（既有导出一行不动）；两个组件自有样式用 `xxai-history-*` 前缀的 scoped 样式，随既有单一样式文件输出。
- 必要配套：新增 `src/ui/markdown/optional-engines.ts`，`mermaid-renderer.ts` / `echarts-renderer.ts` 改从它取说明符。原因是原代码里 `const specifier = 'mermaid'` 被打包器常量折叠，`dist` 中退化成静态 `import("mermaid")`，宿主即使不装图表引擎也会在 dev 预打包与生产构建阶段直接报 `Failed to resolve import "mermaid"`，与「可选依赖、缺失即降级为代码块」的设计相悖；改为跨模块映射后 dist 里保持非字面量 `import(Dc.mermaid)`。
- 必要配套（样式）：`src/ui/styles/index.css` 里 46 个 `--agent-*` 主题令牌原先只声明在 `.xxai-chat-window` 上，而全库 135 处 `var(--agent-*)` 都没有 fallback ⇒ 消息组件渲染在聊天窗口之外时变量全部解析为空，页面退化成无底色、无圆角、无阴影的裸结构（后台 `/conversations` 最初就是这样）。改为把令牌块单独拆出、选择器写 `.xxai-chat-window, .xxai-history-root`，窗口自身的 `position: fixed` 等布局属性留在原 `.xxai-chat-window` 块；`ConversationList.vue` / `ConversationHistory.vue` 根元素加 `xxai-history-root` 接住令牌，消息画布沿用窗口那层 `--agent-background-gradient`（气泡是半透明磨砂白，需要这层浅色渐变才有对比），会话列表对齐既有侧栏的磨砂面与「透明行 + 悬停提亮」交互。
- `package.json`：`scripts` 增加 `prepare: npm run build`（对 npm / registry 消费者有效）。**实测 pnpm 的 `file:` 依赖不执行该钩子**，故「克隆后先构建 SDK」作为人工前置步骤写进两个 README，不宣称自愈。

**前端 `apps/front/`**

- `package.json`：`xxai-agent` 由 `^0.1.6` 改为 `file:../ai-sdk`（与 `apps/shop` 一致），同步 `pnpm-lock.yaml`。
- `src/api/conversation.ts`：后台会话读接口的类型与请求（新接口分页信封是 `page/page_size`，本文件内自行归一为 `{items,total,page,pageSize,totalPage}`），并导出 `createConversationHistorySource()` 实现 SDK 的 `ConversationHistorySource`。
- `src/features/conversations/{index.tsx,principal-detail-page.tsx,conversation-detail-page.tsx,components/{vue-island,conversation-list-island,conversation-history-island,platform-picker,use-active-platform}}`：三层页面；SDK 的 Vue 组件通过 `createApp` 挂载的「Vue 岛」嵌入，一次性 props 快照 + 依赖键变化时重建；列表沿用仓库既有 Table + PAGE_SIZE + react-query 范式，平台选择沿用 `platformId ?? platforms.data?.[0]?.id` 范式。
- `src/routes/_authenticated/conversations/{index.tsx,$principalType.$principalId.tsx,$conversationId.tsx}`：只做 zod search 校验 + 挂载 feature（`src/routeTree.gen.ts` 随之重新生成，需一并提交）。
- `src/components/layout/data/sidebar-data.ts`：AI 管理分组新增「会话记录」项。
- `src/features/tasks/task-detail-page.tsx` 与 `src/features/workflows/workflow-detail-page.tsx`：「查看会话 #N」改指新路由（原先指向后端不存在的 `/chats`）。
- `vite.config.ts`：`server.proxy['/api'].target` 支持用 `VITE_PROXY_TARGET` 覆盖，便于把 dev server 接到临时后端实例做联调。
- `docker-compose.yml` 的 `front` 服务改为以仓库根为构建上下文（`context: .` + `dockerfile: apps/front/Dockerfile`），`apps/front/Dockerfile` 改成三阶段：先构建 `apps/ai-sdk` 的 `dist`，再在 `/app` 安装并打包 front，使 `file:../ai-sdk` 解析到镜像内的 `/ai-sdk`；新增根 `.dockerignore`。原先是 `context: ./apps/front`，pnpm 会把 `file:../ai-sdk` 解析成上下文外的 `/ai-sdk` 并以 ENOENT 失败（`ENOENT … scandir '/ai-sdk'`）。

**其它**：`CONTEXT.md` 新增术语「会话」「会话主体」「会话记录」；新增 `docs/adr/0003-conversation-history-read-boundary.md`；`apps/ai-sdk/README.md` 新增「会话历史组件」章节并注明「改源码后先构建 SDK 再装宿主」，`apps/front/README.md` 同步该前置步骤；同步 `docs/CHANGELOG.md`。

**接口契约（已冻结，三处实现按此对齐）**

- `GET /platforms/{platform_id}/conversation-principals` → `data = {items:[{principal_type, principal_id, display_name, conversation_count, last_conversation_at}], total, page, page_size}`
- `GET /platforms/{platform_id}/conversations` → `data = {items:[{id, platform_id, agent_id, agent_name, principal_type, principal_id, principal_name, title, status, message_count, last_message_preview, last_message_at, created_at}], total, page, page_size}`
- `GET /platforms/{platform_id}/conversations/{id}` → 上述单项 + `{usage:{prompt_tokens, completion_tokens, total_tokens, record_count}}`
- `GET /platforms/{platform_id}/conversations/{id}/messages` → `data = ConversationMessageRead[]`（**裸数组、不分页**，与 embed 同接口逐字段相同）
- `DELETE /platforms/{platform_id}/conversations/{id}` → `data = null`
- SDK：`ConversationHistorySource.listConversations(params) => ConversationPagePayload`、`listMessages(id) => ConversationMessagePayload[]`；`ConversationList.vue` props `{source, params?, emptyText?}` emit `select`；`ConversationHistory.vue` props `{source, conversationId, showAgentLoop?, emptyText?}`，内部用既有 `ChatMessage.vue`（其 `agent?` 可缺省）渲染，`showAgentLoop` 透传给 `showAgentSteps`。

## 验收标准

1. 非平台管理员访问 `/api/v1/platforms/{platform_id}/conversation-principals` 与 `/conversations*` 一律 404（不泄露存在性）；管理员访问其它平台同样 404。
2. 主体列表只列出**有会话**的主体，`conversation_count` 与 `last_conversation_at` 与库内该主体的会话一致；终端用户显示名按 `display_name` → `external_user_id` 回退。
3. `GET .../conversations/{id}/messages` 与同一会话的 `GET /api/v1/embed/conversations/{id}/messages` 在相同数据下返回**逐字段相同**的 payload（含 `loop.steps`）。
4. 列表默认不返回 `status='deleted'` 的会话；软删除后该会话从默认列表消失，而消息与 `model_usage_records` 仍可查；显式 `status=deleted` 时可见。
5. `agent_id`、`start_date`/`end_date`、`keyword`、`principal_type`+`principal_id` 四个筛选维度各自生效且可组合；`keyword` 能命中 `title` 与末条消息摘要两种来源。
6. ai-sdk 构建后：`dist/style.css` 仍存在且仍是唯一 CSS 产物；既有导出（`createAgentClient`/`ChatWidget`/`MarkdownContent`）与既有 `xxai-*` 规则未减少；`ConversationList`/`ConversationHistory` 可从包主入口 import；`type-check` 通过；`--agent-*` 令牌在 `.xxai-chat-window` 之外（`.xxai-history-root`）同样可取到，`mermaid`/`echarts` 仍是可选懒加载（dist 里无静态 import）。
7. `apps/front` 以 `file:../ai-sdk` 安装后 `pnpm exec tsc -b` 通过、`pnpm lint` 不新增 error（存量 4 条基线除外），且 `/conversations` 三层页面在真实后端下可用（表头、分页、筛选、Agent 过程展开各一次真实点击），页面上的消息与 Agent 过程卡片带 SDK 主题令牌解析出的底色/圆角（浏览器断言 `--agent-card` 非空、画布有渐变、气泡非全透明）。

**验证方式**：`tools/harness/verify/2026-10-13-admin-conversation-history.sh` 逐条执行——`pytest tests/conversation -q`（新增 `tests/conversation/test_admin_conversation_read.py` 覆盖验收 1–5，含 admin 与 embed 投影逐字段比对）、`ruff check`、`apps/ai-sdk` 的 `npm run type-check` 与 `build`（断言验收 6）、`apps/front` 的 `pnpm exec tsc -b --force`、`eslint`（按存量基线判定）、`vite build`；另有真实 Postgres 联调（本地 uvicorn）、`docker compose build front` 与容器托管检查（验证容器里能完成 SDK + front 的安装打包，且 nginx 能返回首页、产物含会话记录前端代码）与真实浏览器三层页面点击（`tools/harness/verify/2026-10-13-admin-conversation-history.browser.mjs`，缺 node/playwright/数据库/docker 时记为未执行项）。
