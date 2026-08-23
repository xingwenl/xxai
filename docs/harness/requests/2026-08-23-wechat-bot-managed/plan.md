# 实施计划：后台可管理的微信助手（MVP2）

## 实施步骤

1. 数据模型：`app/modules/wechat_bot/models.py` 新增 `WeChatBotBinding`（表 `wechat_bot_bindings`，
   含 platform_id/user_id/agent_id/加密 bot_token/api_token_hash/状态/扫码凭据，字段带中文注释）。
2. Alembic 迁移：`migrations/versions/20260823_0022_wechat_bot_bindings.py`（down_revision=20260813_0021）；
   `migrations/env.py` 注册 `wechat_bot.models`。
3. 认证扩展：`app/core/security.py` 新增依赖 `require_current_user_or_wechat_service`：
   优先解析用户 JWT；否则按 `Authorization: Bearer <服务 token>` 命中
   `wechat_bot_bindings.api_token_hash`（sha256 + compare_digest），返回绑定用户。
4. chat 接口：`app/modules/conversation/router.py` 的 `chat_endpoint` 改用上述依赖
   （`_prepare`/`execute_chat` 全复用，会话归属绑定用户）。
5. 仓库与 schemas：`app/modules/wechat_bot/repositories.py`（绑定 CRUD + 按 token 查绑定）、
   `schemas.py`（创建/读取/更新/状态）。
6. 服务层：`app/modules/wechat_bot/services.py`：
   - 创建绑定：调 `ILinkApi.get_qr_code()` 拿二维码，生成服务 token（`secrets.token_urlsafe`，
     存 sha256），状态 pending；
   - 轮询状态：调 `ILinkApi.poll_qr_status()`，confirmed 后 Fernet 加密保存 bot_token、
     记录 ilink 账号信息并置 active；expired/失败更新状态与 last_error；
   - 解绑/更新：清敏感字段、置 disabled；agent 绑定与启停。
7. 管理 API：`app/modules/wechat_bot/router.py`（prefix `/platforms/{platform_id}/wechat-bots`，
   依赖 `require_current_active_user` + 平台管理员校验）：列表/创建/状态轮询/更新/解绑；
   `app/__init__.py` 挂载。
8. worker 改造：
   - `app/modules/wechat_bot/chat_client.py`：httpx 调 `POST {api_base}/api/v1/agents/{agent_id}/chat`
     （Bearer 服务 token，非流式），返回 content；
   - `worker.py`：按 active 绑定启动多 `WeChatBot` 实例（上限 20），每实例独立
     状态目录与游标持久化；消息 → chat_client → 回复；周期性刷新绑定
     （新增拉起、解绑/停用/过期即 stop）；-14 后经 on_error 将绑定置 expired。
9. 配置与部署：`config.py` 新增 `WECHAT_BOT_API_BASE_URL`、`WECHAT_BOT_MAX_INSTANCES`；
   `docker-compose.yml` 的 `wechat-bot-worker` 透传并依赖 api/db。
10. 测试：服务 token 认证、管理 API（创建/轮询/解绑/权限）、chat_client、worker 实例管理（mock SDK）。

## 测试步骤

- `poetry run pytest tests/wechat_bot tests/conversation tests/agent -q`：新增与回归全绿。
- `poetry run ruff check app/modules/wechat_bot app/core/security.py app/modules/conversation/router.py`：无告警。
- `PYTHONPYCACHEPREFIX=/tmp/pyc-cache poetry run python -m compileall -q app/modules/wechat_bot`：无语法错误。
- `docker compose config`：解析成功且含 `wechat-bot-worker` 新环境变量。
- 人工联调（需真实微信账号）：后台创建绑定 → 扫码 → active → 微信对话经 chat 接口回复；
  后台可见会话记录；解绑后实例停止。

## 回滚说明

- 迁移回滚：`alembic downgrade 20260813_0021` 删除 `wechat_bot_bindings`。
- 代码回滚：移除 `wechat_bot` 模块新增文件、chat 接口认证分支、worker 多实例改造与 compose 环境变量。
- 服务 token 与 bot_token 随绑定记录删除/置空；无额外数据库回滚。

## 变更记录

- 初始版本：2026-08-23，MVP2 实施计划（spec 已获用户全部决策点确认）。

### 2026-08-23 第 1 次变更（实现期调整）

- 变更内容：实现中增加 `api_token_encrypted` 列（worker 持明文服务 token 调 chat 接口）、
  chat 接口认证依赖替换、删除 `agent_bridge.py`/`WECHAT_BOT_AGENT_ID` 旧单实例链路、
  `Dockerfile.wechat-bot` 去掉重复安装。
- 影响测试步骤：新增用例覆盖服务 token 认证相关仓库查询、绑定服务、chat 客户端。

### 2026-08-23 第 2 次变更（前端管理台）

- 变更内容：`apps/front` 新增微信助手管理页面（平台选择、列表、新建扫码、状态轮询、解绑）。
- 影响测试步骤：前端 `tsc -b`、`eslint`、`vite build` 均通过。

### 2026-08-23 第 3 次变更（fix：扫码绑定流程）

- 变更内容：pending 可重新生成二维码；补全 need_verifycode/verify_code_blocked/
  scaned_but_redirect 状态机；新增 verify-code 提交接口与前端配对码输入。
- 影响测试步骤：新增 5 个服务层用例（pending 复用、配对码、重定向等），
  `tests/wechat_bot` 共 18 个用例全绿。

### 2026-08-23 第 4 次变更（fix：微信对话上下文复用）

- 变更内容：worker 原先调 chat 接口未携带 `conversation_id`，后端每次新建会话导致
  记不住上下文。本次为每个微信用户（私聊联系人 / 群聊房间）在 `state.json` 持久化
  conversation_id 映射，聊天时携带以复用历史；会话失效（404）时自动清除映射并用
  新会话重试一次。仅改 worker 本地状态，无数据库/API 契约/鉴权变化。
- 影响测试步骤：`chat_client` 新增 conversation_id 透传与 404 用例，
  `session` 新增映射读写/清理用例，`tests/wechat_bot` 共 24 个用例全绿。
