# 智能体切换：平台开关 + 宿主提供候选列表

## Status

accepted

关联 Harness request：`docs/harness/requests/2026-10-21-ai-sdk-agent-switching/`（tier A，spec 与验证证据见该目录）。
术语（智能体切换、可用智能体、智能体切换开关）见 `CONTEXT.md`。
本 ADR 回答三个问题：开关为什么放在后端 embed client 而不是 SDK，候选列表为什么由宿主传而不是后端接口，切换为什么是「先换 token 再断连」的两阶段操作。

## Decision

1. **开关是平台策略，放在 `PlatformEmbedClient.allow_agent_switching`，不是 SDK 配置项。** 「能不能让终端用户换智能体」取决于这个接入方被授予的权限与绑定了哪些 agent，属于平台侧治理；同一 client 可能被多个宿主页面接入，如果开关写在 SDK options 里，每个宿主各写一次、管理员无法统一关闭，等于没有开关。数据库列默认 `false`，存量 client 升级后保持关闭。
2. **开关经 `session_ready` 的 client 快照下发，不进 token claim。** token 生命周期 300–900s 且 SDK 按 exp 缓存复用，把策略放进 claim 会留下最长 15 分钟的旧策略窗口；`session_ready` 每次建连刷新，语义准确，且完全复用既有快照通道（client/agent/quota 已在同一结构里）。
3. **候选列表由宿主提供（`agentSwitching.agents`），不新增「SDK 携 embed token 拉列表」的接口。** embed 接入是「平台管理员配置 client → 第三方宿主页面嵌入」，只有宿主知道自己要暴露哪些 agent 给终端用户；新增公开列表接口会多一个对外鉴权面与 SDK/后端版本耦合点，而换 token 时服务端仍用 `is_agent_allowed` 校验绑定，越权在选择那一刻就会被拒——安全性不依赖列表的正确性，只依赖服务端的绑定校验。
4. **SDK 的两个前提条件必须同时满足才展示入口：`clientInfo.allowAgentSwitching === true` 且 `agentSwitching.agents` 非空。** 任一不满足即不渲染、`switchAgent()` 直接返回 `false`；关闭开关后即便调用方硬调也无效，避免「UI 关了但 API 还能换」。
5. **切换是两阶段操作：先为目标 agent 预签 token，成功后才断开重连。** token 是切换唯一可能因「未绑定 / 无权限 / 配额」而失败的外部依赖；先预签把失败前置到「什么都没动」的时刻。失败时保留原 agent 的连接、消息、待确认与 token 缓存，通过 `callbacks.onError` 上报并 emit `agent_switch_failed`，文案区分「未绑定 / 无权限」与「网络 / 配额」。
6. **切换成功后按目标 agent 的本地存储恢复它上次的会话。** 本地存储 key 本来就含 `agentId`（`xxai-agent:${platformId}:${agentId}:${user}`），各 agent 天然隔离；恢复比「新建空会话」更符合「切回去继续刚才的事」。`storageKey` 因此从构造期常量改为按 active agent 派生的 getter。
7. **会话上下文不跨 agent 迁移。** 两个 agent 的模型、系统提示、工具集、绑定知识库都可能不同，迁移历史会污染上下文；后端会话本身也按 `agent_id` 隔离，技术上无法续用。
8. **记住上次选中的 agent，但记忆受开关与失败约束。** key 为 `xxai-agent:selected-agent:${platformId}:${user}`；构造时按记忆决定首连目标（避免「先连默认再切换」的双连接），连接成功后若快照显示开关已关闭，则回退默认 agent 并清除记忆，保证「管理员关掉 = 记忆自动失效」。记忆写入只在切换成功后发生。
9. **忙碌时禁止切换。** 生成中、等待工具确认、等待提问回答、压缩中重建 transport 会丢事件与 token 流；此时选择器置灰并给出原因，不排队、不静默丢弃。
10. **重建 transport 后必须重注册宿主工具并清空待确认/待提问状态。** `WebSocketTransport` 的已注册工具是实例内状态，重建即丢；待确认的工具调用与待回答的问题属于旧连接，跨 agent 转发会打到错误的会话，一律清空。
11. **切换能力对 headless 用户同样开放。** 除 UI 外公开 `availableAgents` / `canSwitchAgent` / `switchAgent()`，让自绘 UI 的宿主复用同一套校验与两阶段语义，避免 UI 与程序化路径两套行为。
12. **`apps/front` 接入时用后台登录态自行求交集；当前 Client 由后端签发的 Embed token 载荷里读取，`VITE_AGENT_CLIENT_ID` 只是多 Client 部署的显式覆盖。** 最初让宿主必填 `VITE_AGENT_CLIENT_ID`，实测该变量一旦漏配，切换入口会静默消失且没有任何可见线索——而 token 的 `client_id` claim 本来就是「后端拿哪个 Client 签的」的唯一事实，宿主重复维护一份只会漂移。拿不到 Client 或取候选失败时仍整体关闭入口；浮动助手是旁路能力，绝不能因为拿不到候选列表而影响主壳挂载，与 bridge 现有 `skipAuthReset` 的失败隔离思路一致。

## Considered Options

1. **后端新增公开列表接口 `GET /embed/agents`** —— 列表最权威、宿主零逻辑；但新增对外鉴权面与版本耦合面，而服务端绑定校验已经提供最终防线。
2. **开关写成 SDK 配置项** —— 接入时一行代码即可开；但同一 client 的多个宿主行为不一致，管理员失去统一关闭能力。
3. **开关放进 token claim** —— 一次签发处处生效；但最长 900s 的策略滞后与缓存复用会导致「后台已关、仍能切换」。
4. **切换时新建空会话** —— 语义最简单；但用户切回原 agent 会丢上下文。
5. **带着当前会话历史切到新 agent** —— 体验上最连续；但上下文污染、后端按 agent 隔离，不可行。
6. **直接复用后台管理接口给 SDK** —— 零新增接口；但要求公开包假设宿主有管理员登录态，且返回体不含名称/描述。
7. **忙碌时排队切换（等当前运行结束再切）** —— 用户点击立即生效；但排队期间界面处于「已选未切」的中间态，失败与取消路径都要设计，收益不抵复杂度。
8. **切换时保留旧连接的 pending 确认/提问** —— 少一次清空；但会把旧 agent 的调用转发到新连接，等于串会话。
9. **选中项只存内存不持久化** —— 实现最省；但刷新即回默认，用户会认为选择器坏了。

## Consequences

- 新增一列 + 一次 migration，语义向后兼容：存量 client 默认关闭，SDK 未配置 `agentSwitching` 时行为与今日完全一致。
- 宿主多了一份「取候选列表」的责任：`apps/front` 从 Embed token 的 `client_id` claim 定位当前 Client（可用 `VITE_AGENT_CLIENT_ID` 覆盖）后求「启用 agent ∩ 已绑定 agent」；其他宿主（desktop/shop）不接入即不启用。
- 列表与真实绑定可能不一致（管理员改了绑定而宿主列表未刷新）：表现为切换失败并提示，不会造成越权——服务端绑定校验是最终防线。
- 首连目标由本地记忆决定时，用户可能先看到「上次选的那个 agent」而不是 `VITE_AGENT_ID`；这是有意行为，且开关关闭时会自动回退。
- `storageKey` 从只读属性变为 getter，对外表现不变（首次渲染仍是同一字符串），但任何在构造后缓存该值的宿主代码需要重新取值。
- 每次成功切换会重建 WebSocket 连接，服务端表现为「断开 + 新连接」；对 max_connections 配额的影响与用户刷新页面相同，本期不做连接复用优化。
- 切换失败是新增的可观测事件（`agent_switch_failed` + `callbacks.onError`），宿主可据此上报；本期不做自动重试。
