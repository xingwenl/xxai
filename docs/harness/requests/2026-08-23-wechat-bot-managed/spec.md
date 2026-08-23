# 设计说明：后台可管理的微信助手（绑定/解绑 + 用户级鉴权）

## 目标

- 将微信 ClawBot 从「单账号全局配置」升级为「后台用户可自助管理的微信助手」：
  后台用户可将自己的微信号绑定为助手（扫码），可解绑；绑定关系落库；
  worker 以绑定用户身份运行完整对话链路（智能体/知识库/技能/工具与后台一致）。
- 完成后应产生的可验证结果：后台用户登录后可在管理接口添加微信助手（获取二维码）、
  轮询绑定状态、查看列表、解绑；已绑定微信号能通过对应智能体收到 AI 回复；
  解绑后该实例停止轮询。

## 范围

- 新增数据模型 `wechat_bot_bindings`（需 Alembic 迁移）：
  - `platform_id`（FK platforms）、`user_id`（FK sys_users，绑定的后台用户）；
  - `agent_id`（FK agents，可空：空则用平台默认智能体，非空则固定该智能体）；
  - `bot_token`（Fernet 加密）、`ilink_bot_id`、`ilink_user_id`；
  - 绑定状态 `pending / active / disabled / expired`、扫码二维码与状态轮询凭据、最后错误信息、时间戳。
- 新增后台管理 API（前缀 `/platforms/{platform_id}/wechat-bots`，均需
  `require_current_active_user` + `require_platform_admin`）：
  - `GET` 列表；`POST` 创建绑定（返回二维码）；`GET /{id}/status` 轮询扫码状态；
  - `DELETE /{id}` 解绑（清 token 并停止实例）；`PATCH /{id}` 修改 agent 绑定与启停。
- 认证扩展：`/api/v1/agents/{agent_id}/chat` 新增「微信助手服务 token」认证分支——
  校验 `Authorization: Bearer <服务 token>` 命中 `wechat_bot_bindings.api_token_hash`
  后，按绑定记录的 `user_id` 作为当前用户继续原有 `_prepare` 链路
  （`get_published_agent_for_user` 权限校验、`load_runtime_context`、`execute_chat` 全复用）。
- worker 改造：
  - 启动时加载全部 active 绑定，每绑定一个独立 `WeChatBot` 实例并发长轮询；
  - 周期性刷新绑定列表：新增立即拉起、解绑/停用即停止对应实例；
  - 收到消息后以绑定记录的 `agent_id + 服务 token` 调
    `POST /api/v1/agents/{agent_id}/chat`（非流式），取返回的 `content` 回复微信；
  - 新增配置 `WECHAT_BOT_API_BASE_URL`（容器内默认 `http://api:8000`）。
- 新增测试：绑定仓库/API 用例、worker 多实例管理用例（mock SDK）。
- 新增后台前端（`apps/front`）：「AI 管理 → 微信助手」页面，支持平台选择、绑定列表、
  新建绑定（选智能体 + 二维码展示 + 服务 Token 一次性展示 + 扫码状态轮询）、解绑。
- 文档：本 request 的 research/spec/plan/verify/acceptance/meta。

## 非目标（本轮）

- 不实现消息历史展示、主动推送（平台协议限制）。
- 对话消息经 chat 接口正常落库（conversation/message/loop，归属绑定用户，后台可见对话记录）。
- 不实现多平台跨租户的微信助手市场/共享。
- 不实现消息历史、主动推送（平台协议限制）。

## 风险

- 多实例并发长轮询：单容器内实例数增加会放大单点故障面，需容量评估（MVP2 默认上限如 20）。
- 扫码绑定是外部账号操作：二维码过期、绑定冲突（微信号已被其他平台绑定）需明确提示与重试。
- `bot_token` 敏感凭证：加密落库、日志脱敏、解绑即清除。
- 服务 token 安全：随机生成、绑定表存 hash、日志脱敏；token 泄露仅影响对应绑定用户会话。
- 落库数据增长：微信对话会随后台会话一起落库，需后续考虑生命周期清理。
- 定时刷新与实例启停的一致性：解绑瞬间与轮询恢复之间需有幂等保障。

## 停点判断

- 是否涉及架构边界变化：是（worker 从单账号升级为多账号实例管理）→ 需人工确认
- 是否涉及数据模型变化：是（新增 `wechat_bot_bindings` 表）→ 需人工确认
- 是否涉及 API 契约变化：是（新增 `/platforms/{platform_id}/wechat-bots` 系列接口）→ 需人工确认
- 是否涉及鉴权或权限行为变化：是（后台用户管理自己的微信助手；worker 以绑定用户身份对话）→ 需人工确认
- 结论：进入实现前必须完成本 spec 的人工确认。

## 待用户确认的决策点

1. 每用户绑定数量：建议 MVP2 先限制「每个平台管理员最多 1 个微信助手」（唯一约束
   `platform_id + user_id`），后续再放开多账号；→ **已确认：每个用户 1 个微信号**
2. token 方案：按你的思路——绑定表内生成长期「服务 token」（存 hash），
   chat 接口新增 Bearer 服务 token 认证分支（解析为绑定用户）；→ **已确认**
3. 对话消息落库：走 chat 接口会正常落库（归属绑定用户，后台可见对话记录）；
    → **已确认：接受落库**
4. 后台前端界面：建议本轮只做 API + worker 改造，前端接入下一轮；→ **已确认（按推荐）**
5. 智能体归属：建议绑定记录可指定 `agent_id`（空则用平台默认智能体）；→ **已确认（按推荐）**
6. worker 实例上限：建议 MVP2 上限 20 个同时在线实例；→ **已确认（按推荐）**

> 2026-08-23 全部决策点已获用户确认，本 spec 可作为实现依据。

## 验收标准（草案）

- [ ] Alembic 迁移后新增 `wechat_bot_bindings` 表，字段含中文注释。
- [ ] 后台 API：创建绑定返回二维码、状态轮询到 `active`、列表可见、解绑后绑定记录失效。
- [ ] worker 多实例：两个不同账号绑定后各自独立收发消息；解绑一个不影响另一个。
- [ ] 对话链路：worker 以服务 token 调 chat 接口成功，微信回复使用绑定智能体，后台可见对应会话记录。
- [ ] 权限：无平台管理员权限的用户无法创建/管理该平台微信助手。
- [ ] 自动化验证：新增用例全绿，既有 `tests/agent`、`tests/conversation` 无回归。

## 变更记录

- 初始版本：2026-08-23，创建 request（MVP2：后台可管理的微信助手）。

### 2026-08-23 第 1 次变更（实现期调整）

- 变更原因：实现过程中为支撑「worker 调 chat 接口」补齐凭证与链路细节
- 变更内容：
  - `wechat_bot_bindings` 增加 `api_token_encrypted` 列（服务 token 明文 Fernet 加密，
    供 worker 调用 chat 接口；`api_token_hash` 用于接口认证）；
  - chat 接口认证依赖改为 `require_current_active_user_or_wechat_service`
    （优先用户 JWT，其次绑定服务 token）；
  - 删除被多实例架构取代的 `agent_bridge.py` 与旧单实例配置 `WECHAT_BOT_AGENT_ID`；
  - `Dockerfile.wechat-bot` 移除冗余 `pip install wechatbot-sdk`（已入主依赖）。
- 影响章节：范围（数据模型、worker、认证）
- 是否触发人工确认：否（属已确认方案的实现细节，未改变决策点边界）

### 2026-08-23 第 2 次变更（前端管理台）

- 变更原因：用户确认后询问「管理台没写吗」，期望本轮包含后台界面
- 变更内容：`apps/front` 新增「AI 管理 → 微信助手」页面（`features/wechat-bots`、
  `api/wechat-bots.ts`、路由 `/ai/wechat-bots`、侧边栏菜单），覆盖列表/新建扫码/
  状态轮询/解绑全流程。
- 影响章节：范围（新增前端页面）
- 是否触发人工确认：否（用户明确期望管理台，属于原决策点 4 的方向修正）

### 2026-08-23 第 3 次变更（fix：扫码绑定流程）

- 变更原因：人工联调发现两个问题——扫码后未绑定成功；pending 状态无法再次弹出二维码绑定
- 变更内容：
  - `create_binding`：已存在未生效（pending/expired/disabled）绑定时复用记录重新生成
    二维码与服务 token，仅 active 才要求先解绑；
  - 补全轮询状态机：`need_verifycode`（配对码）、`verify_code_blocked`、
    `scaned_but_redirect`（IDC 重定向，更新轮询基址）；
  - 新增 `POST /wechat-bots/{id}/verify-code` 提交配对码接口；
  - `wechat_bot_bindings` 新增 `qrcode_base_url`、`pending_verify_code` 列（迁移 `20260823_0023`）；
  - 前端轮询支持配对码输入与提交。
- 影响章节：范围（绑定流程、数据模型、API、前端）、验收标准
- 是否触发人工确认：否（bug 修复，未改变已确认边界）

### 2026-08-23 第 4 次变更（fix：扫码状态轮询卡死）

- 变更原因：人工联调发现前端状态一直显示「等待扫码...」，实际已扫码——
  轮询请求一旦失败（axios 10s 超时等）即永久停止，界面停留在初始文案且无失败提示
- 变更内容：
  - 后端 `poll_binding_status` 增加 `asyncio.wait_for`（10s）超时保护，
    超时记录 last_error 并返回 error；每次轮询输出真实状态日志
    （`wechat qr poll binding_id=... status=...`）；
  - 前端轮询失败不再停死：显示「状态查询失败，正在自动重试...」并继续轮询；
    新增「重新查询状态」手动按钮；`verify_code_blocked` 加入终止条件。
- 影响章节：范围（绑定流程）、验收标准
- 是否触发人工确认：否（bug 修复）

### 2026-08-23 第 5 次变更（平台内置工具扩展：http_post）

- 变更原因：微信联调发现模型只能用 `http_get`（GET），掘金等公开 API 需 POST 请求，
  模型无法完成任务并返回空回复
- 变更内容：
  - 新增内置工具 `http_post`（`builtin_tool/http_post.py`）：向公开 URL 发送 POST +
    可选 JSON 请求体，安全约束与 `http_get` 一致（SSRF 防护、无认证、大小限制）；
  - `registry.py` 注册目录、`services.py` 按工具名分发；
  - 迁移 `20260823_0024`：已启用 `http_get` 的智能体自动启用 `http_post`。
- 影响章节：范围（平台内置工具目录）、验收标准
- 是否触发人工确认：否（工具目录扩展，复用既有安全约束，未改变鉴权/数据模型/API 契约）
