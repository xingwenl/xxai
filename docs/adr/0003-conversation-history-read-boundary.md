# 会话记录走后台平台级只读路由，ai-sdk 只交付展示组件而不持有数据源

## Status

accepted

关联 Harness request：`2026-10-13-admin-conversation-history`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-13-admin-conversation-history/`）。

## Decision

**读侧契约**：后台的会话记录接口自成一组，挂在 `/api/v1/platforms/{platform_id}/conversation-principals` 与 `/conversations` 系列下，与既有的 embed-claims 作用域接口（`GET /api/v1/embed/conversations`）并存而不是合并。两组接口的隔离依据不同——embed 侧的平台、终端用户、Agent 全部取自 embed token 的 claim，调用方无法用参数越权；后台侧的可见范围是「平台内的全部会话」，由 `PlatformRepository.get_by_id_for_user` 判定平台管理员身份（非管理员 404 而非 403，沿用本仓库既有约定）。把两者合并成一套接口，就意味着后台请求里也要带上「以谁的身份看」这类可被构造的参数，那才是真正危险的形状。

**投影唯一**：消息与 Agent Loop 的返回结构只有一个构造点。把 `apps/backend/app/modules/embed/services.py` 里 `get_embed_message_snapshot` 内联的投影构造抽成 `apps/backend/app/modules/conversation/serializers.py` 的 `build_message_snapshots(repo, *, conversation_id, messages)`（含 `build_loop_payload`、`conversation_preview`），embed 接口与后台接口都调它。因此「管理员看到的会话内容」与「终端用户看到的会话内容」不是两份约定，而是同一份代码的两次调用。

**SDK 边界**：`xxai-agent` 只交付两个展示组件（`ConversationList`、`ConversationHistory`）与一个 `ConversationHistorySource` 接口，**不实现 HTTP、不认识后台路径、不持有鉴权**。请求实现由宿主放在 `apps/front/src/api/` 下注入。SDK 侧唯一负责的转换是「后端 payload → SDK `Message`」，且这份映射从 `apps/ai-sdk/src/core/client.ts` 既有的 `fetchHistory` 里抽出来共用，保证后台看到的 Loop 呈现与 embed 聊天窗口里的完全同源。

**复用方式**：在主入口**追加导出**，不新增子路径导出、不把 `build.lib.entry` 改成多入口、不改 `exports`、不动既有 `dist/style.css` 的文件名与既有导出。新组件的样式用 `xxai-history-*` 前缀的 scoped 样式，随既有单一样式文件一起输出。

**删除语义**：软删除（`conversations.status = 'deleted'`），列表默认隐藏、筛选项可显式查看。这与 embed 侧一致，原因是 `model_usage_records.conversation_id` 是 `ondelete=CASCADE`，物理删除会连带销毁计费数据。

## Considered Options

- **让 ai-sdk 自带 HTTP 实现（`createHttpHistorySource({baseUrl, platformId, getToken})`）**：宿主接入成本最低，看起来最像「直接装进来」。否决理由有两层。其一是仓库边界：`docs/harness/frontend.md` 要求 `src/api/` 统一封装后端接口、禁止请求散落在业务模块之外，而 SDK 是跨 app 复用的库，一旦它自己发请求，这条边界在「哪个 app 的 token、哪个平台的隔离」上就失效了。其二是可逆性：后台接口路径、分页参数、鉴权方式只要变一次，就得发一个 SDK 版本，而 SDK 的消费者还包括 `apps/shop` 这类与本需求无关的宿主。
- **把 ai-sdk 的整块 Vue 聊天岛嵌进后台**：省掉全部前端列表代码。否决理由是不能工作而非不好看——ai-sdk 只打 embed-claims 作用域接口，管理员 token 打不通；要接通只能伪造一个 embed token，等于把「以终端用户身份读会话」变成后台的一条常规路径，这与本 request 想建的权限面（管理员以管理员身份读本平台会话）正好相反。此外它的浮窗按钮是 `position:fixed; z-index:9999`，与后台现有的 agent 导航浮窗冲突。
- **为 ai-sdk 增加子路径导出 `xxai-agent/history` + `history.css`**：隔离最干净，老宿主连体积都不受影响。否决理由是构建事实：lib 模式下 `cssCodeSplit` 默认 false，全库样式汇成单个 `dist/style.css`；要拆出独立 CSS 就必须打开 `cssCodeSplit`，而其输出命名变化会波及既有宿主对 `xxai-agent/style.css` 的 import——这恰好是用户明确要求的「不影响 ai-sdk 以前的功能」。追加导出 + 复用既有单一样式文件是同一目标下风险更低的实现。
- **给 `conversations` 加 `message_count` 与 `last_message_at` 冗余列**：列表查询会更快。否决理由是它是数据模型变化，而且要与三条写入路径（`conversation/services.py` 的 `execute_chat`、`stream_chat` 与 gateway 的落库）同时保持同步，任一路径漏更新就会出现「列表数字与详情对不上」这类难查的错。现有的两条相关子查询（`ConversationRepository.list_for_principal` 的消息数与末条消息摘要子查询）已经把同一件事在 embed 侧做过一遍并通过验证，v1 直接沿用。
- **第一层平铺全部会话，不做主体聚合**：少一次接口与一个页面。否决理由是终端用户的会话量级会随平台增长，平铺之后「谁跟谁的对话」在一屏里混排不可读；用户已经明确要「用户 → 会话列表 → 会话内容」的三层结构。
- **新开 `/api/admin/conversations` 全局前缀**：语义上最像「后台」。否决理由是本仓库不存在全局管理员角色，所有后台面都嵌在 `/platforms/{platform_id}/...` 之下，`sys_roles`/`sys_user_roles` 表虽然存在但授权逻辑从不查；新开全局前缀等于在没有角色模型的前提下另起一套鉴权约定，而「跨平台视图」是另一个 request 的规模。
- **物理删除会话**：语义最干净。否决理由是 `model_usage_records.conversation_id` 上挂着 `ondelete=CASCADE`，删会话会连带删掉计费记录；embed 侧因此早已选择软删除，两处口径必须一致，否则同一个会话在两个入口下的存在性会互相矛盾。

## Consequences

- 后台读侧接口与 embed 读侧接口成为两条平行入口，共享仓储方法与投影函数但不共享守卫。今后任何消息结构的变更都只需改 `serializers.py` 一处，但如果有人绕过它直接拼 payload，两条入口就会静默分叉——`verify` 脚本里的「admin 与 embed 投影逐字段比对」用例就是为这条分叉设的闸。
- 平台管理员从本次起可以读到本平台全部会话的完整正文，其中包含终端用户与 Agent 的原文。这是一个实质的权限面扩张，已作为 `approval.required` 的一项单列；若日后要求脱敏或按 Agent 授权，需要在此接口的守卫上增加维度，而不是改投影。
- `ConversationHistorySource` 由宿主实现，意味着 SDK 无法单方面演进数据契约：接口变更需要 apps/front 同步改 `src/api/conversation.ts`。这是刻意选的代价——换来的是一条可审计的边界：**「谁能读哪些会话」这个问题只在 apps/front 与后端之间回答，SDK 不参与**。
- 主入口追加导出会让既有宿主的产物略微变大（两个组件复用已在 bundle 内的 `ChatMessage`/`AgentLoopPanel`/`MarkdownContent`，所以增量很小），但换来了「不新增构建目标」这一条对已发布库更重要的稳定性。若日后 SDK 的消费者数量增长到需要按入口裁剪体积，再以新 request 引入多入口构建。
- **「追加导出」隐含一条样式契约**：SDK 的 `--agent-*` 主题令牌原先只声明在 `.xxai-chat-window` 上，而组件样式里 135 处 `var(--agent-*)` 都没有 fallback。这在聊天窗口里看不出问题，一旦这些组件被渲染到没有窗口祖先的宿主（后台的 React 壳）就整体退化为无底色、无圆角、无阴影的裸结构——本次 `/conversations` 首次上线即踩到。现在令牌块的选择器写成 `.xxai-chat-window, .xxai-history-root`，窗口自身的布局属性留在原处；**新增任何「可在窗口外渲染」的组件都必须挂 `xxai-history-root` 这一类接 token 的根类**，验证脚本里的浏览器断言（`--agent-card` 非空、画布有渐变、气泡非全透明）是为这条契约设的闸。
- `apps/front` 改用 `file:../ai-sdk` 之后，front 的构建结果开始依赖本地 SDK 的 `dist`。`apps/ai-sdk/dist` 不被 git 跟踪，因此干净克隆下必须能先构建 SDK。实测结论：`package.json` 里加的 `prepare` 在这里**不生效**——把 `apps/ai-sdk/dist` 移走后执行 `pnpm install`，dist 没有被重建、front 拿到的 `node_modules/xxai-agent/dist` 也不存在（pnpm 对 `file:` 依赖是复制，且不跑宿主的 prepare 钩子）。因此这条链条被如实记为「人工前置步骤」并写进 `apps/ai-sdk/README.md` 与 `apps/front/README.md`，而不是假装自愈。这也是本 ADR 里唯一没有自动化保护的一环：CI 或新同学配环境时若跳过 `npm run build`，`apps/front` 的类型检查/构建会以「找不到 xxai-agent 的类型或样式」失败，看到该报错时先补构建即可。
