# 业界调研记录：后台可管理的微信助手（绑定/解绑 + 用户级鉴权）

## 调研问题

- 要解决什么问题？
  - 将上一轮「微信 ClawBot 单账号 MVP」升级为后台可管理的微信助手服务：
    后台用户可将自己的微信号绑定为「微信助手」，绑定关系落库；后台提供
    增加/解绑/列表管理接口；worker 以绑定用户身份运行完整对话链路。
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - 新增数据模型（微信助手绑定表）与迁移；
  - 新增后台管理 API（增/查/删/状态轮询）与鉴权方式（是否新建 token）；
  - worker 部署形态（单容器多账号实例 vs 每账号一容器）；
  - 扫码绑定流程的实现方式（API 轮询 vs 后台任务）；
  - 对话消息是否落库、会话归属。

## 功能复杂度

- 级别：核心功能
- 选择理由：涉及新数据模型、新 API 契约、鉴权模型（用户级凭证）与 worker
  多实例架构，且绑定流程（扫码）是外部账号级操作，需要安全与生产实践分析。

## 现有代码基础（复用点）

- 后台用户鉴权：`app/core/security.py` 的 `require_current_active_user`（JWT），
  `app/modules/agent/router.py` 的 `_require_platform_admin(platform_id, user_id)`
  校验平台管理员归属 —— 后台管理接口直接复用该模式。
- 完整对话链路：`app/modules/conversation/router.py` 的 `_prepare`（`load_runtime_context`
  + 工具 invoke 闭包）与 `execute_chat`；`load_runtime_context` 已支持
  知识库/技能/MCP/内置工具绑定，`get_published_agent_for_user(agent_id, user_id)`
  校验「用户是该智能体平台的平台管理员」—— 与微信绑定的后台用户语义天然匹配。
- SDK 登录原语：`wechatbot/auth.py` 的 `login()`（整体流程），`wechatbot/protocol.py`
  的 `ILinkApi.get_qr_code()` 与 `poll_qr_status()`（可拆分「生成二维码」与
  「轮询状态」两步，供后台绑定 API 使用）。
- 敏感字段加密：`app/modules/agent/services.py` 的 `encrypt_secret/decrypt_secret`
  （Fernet + AGENT_MASTER_KEY）—— 用于加密存储 `bot_token`。
- Embed 客户端模型：`PlatformEmbedClient`（client_id + secret_hash + 签发 JWT）——
  作为「分配 token」方案的现成参考。

## 参考依据

### 来源 1

- 类型：本项目现有实现（代码内调研）
- 名称：embed 模块（PlatformEmbedClient / issue_embed_token）
- 调研日期：2026-08-23
- 核心做法：平台为外部客户端签发 client_id/secret，按平台签发带 audience 的短期 JWT，
  用于 SDK/终端用户访问对话链路；有配额（token/min、连接数）与来源限制。
- 对本项目的启发：若需要「独立服务凭证」，embed 体系是最接近的现成模式；
  但微信 worker 运行于服务端内网且已直连数据库，凭证需求弱于前端 SDK 场景。

### 来源 2

- 类型：本项目现有实现（代码内调研）
- 名称：conversation 完整对话链路（load_runtime_context + execute_chat）
- 调研日期：2026-08-23
- 核心做法：`get_published_agent_for_user` 把「可对话的智能体」限定为当前用户有
  平台管理员权限的已发布智能体；`load_runtime_context` 组装知识库/技能/MCP/内置工具；
  `execute_chat` 落库会话（conversation/message/loop）。
- 对本项目的启发：微信助手绑定到后台用户后，worker 可用绑定记录的 `user_id`
  走同一权限校验与完整链路，实现「与后台一致的智能体能力」。

### 来源 3

- 类型：iLink 协议 / SDK 登录流程
- 名称：wechatbot.dev 协议文档与 wechatbot-sdk auth/protocol 源码
- 调研日期：2026-08-23
- 核心做法：登录为「get_bot_qrcode → get_qrcode_status 轮询 → confirmed 返回
  bot_token/ilink_bot_id/ilink_user_id」；`bot_token` 是账号级敏感凭证；
  单账号同一时刻只能一个实例长轮询（getupdates 游标互斥）。
- 对本项目的启发：绑定流程可拆成「后台生成二维码 → 前端轮询状态 → confirmed 后
  加密保存 bot_token」；多账号 = 每账号一个独立 WeChatBot 实例（不同 token 互不影响）。

## 方案比较

| 方案 | 优点 | 限制 | 推荐度 |
|---|---|---|---|
| A. 独立绑定表 `wechat_bot_bindings`（platform_id + user_id + agent_id + 加密 bot_token + 状态），worker 直连 DB 按绑定记录运行，管理 API 复用现有用户 JWT | 数据模型清晰；worker 无需额外 token（绑定记录即凭证）；直接复用 `get_published_agent_for_user` 权限校验；后台 API 沿用现有鉴权，无新鉴权面 | 需新增迁移；worker 需定时刷新绑定变更 | 高 |
| B. 复用 embed client 体系给每个微信助手发 token，worker 持 token 调 conversation HTTP API | 复用现有鉴权实现 | 语义不匹配（embed 面向终端用户 SDK）；worker 需维护 token 生命周期；消息经 HTTP 多一跳；对话强制落库 | 低 |
| C. 新建独立 API token 表（wechat 助手专用） | 凭证显式、可单独吊销 | 新增一张表 + 签发/吊销逻辑 + worker 持 token 调 API 又回到 HTTP 一跳问题 | 中 |
| D. 每账号一个独立 worker 容器（按绑定记录动态起容器） | 实例隔离强 | 运维复杂度高；绑定变更要编排容器，MVP 阶段过重 | 低 |
| E. 单容器内多 WeChatBot 实例并发长轮询（asyncio），按绑定表 active 记录加载 | 部署简单；天然贴合「单账号单实例轮询」约束；绑定增删只影响对应实例 | 单容器故障影响所有账号；实例上限需容量评估 | 高 |

## 最终决策（待用户确认 spec 后生效）

- 数据模型：新增 `wechat_bot_bindings` 表（方案 A），字段含 platform_id、user_id、
  agent_id（可空，空则用平台默认智能体）、加密 bot_token、ilink_bot_id、ilink_user_id、
  绑定状态（pending/active/disabled/expired）、最后错误、扫码凭据（qrcode 等）、
  api_token_hash（微信助手专用服务 token 的哈希）。
- 认证：后台管理 API 复用现有用户 JWT（require_current_active_user +
  require_platform_admin）；对话走 HTTP 接口——绑定记录内置长期服务 token，
  `/agents/{agent_id}/chat` 新增 Bearer 服务 token 认证分支，解析为绑定用户后
  完整复用 `_prepare`/`execute_chat` 链路（含 `get_published_agent_for_user` 权限校验）。
- worker 形态：单容器多实例（方案 E），启动时加载全部 active 绑定，周期性刷新
  （新增立即拉起、解绑即停）；收到消息调用 chat 接口（非流式），取 content 回复。
- 绑定流程：后台 POST 创建绑定 → 返回二维码 → 前端轮询 status → confirmed 后
  加密保存 bot_token 并置 active；解绑 DELETE 清 token 并停止对应实例。
- 对话链路：经 `/agents/{agent_id}/chat` 完整复用（知识库/技能/工具 + 落库），
  会话归属绑定用户，后台可见微信对话记录。
