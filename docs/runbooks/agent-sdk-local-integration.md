# Agent SDK 本地联调手册

本文用于验证 Phase 2A 的真实 Embed Token、FastAPI WebSocket、Redis Stream 和浏览器 SDK 链路。

## 前置服务

启动 PostgreSQL/pgvector 和 Redis，并确认应用配置中的数据库连接和 `celery_broker_url` 指向这些服务。Redis 测试使用：

数据库表统一使用仓库脚本创建或升级，不需要应用启动时自动建表：

```bash
cd apps/backend
bash scripts/create_tables.sh
```

查看迁移状态：

```bash
bash scripts/create_tables.sh current
bash scripts/create_tables.sh history
```

```bash
cd apps/backend
PHASE2_REDIS_URL=redis://127.0.0.1:6379/15 poetry run pytest tests/gateway/test_replay_integration.py -q
```

## 后端

```bash
cd apps/backend
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload --port 8000
```

由平台管理员创建 Embed Client 并绑定 Agent；接入方服务端调用 `POST /api/v1/embed/tokens` 换取短期 token。浏览器只接收 `access_token`，不得接触 `client_secret`。

也可以配置 `EMBED_CLIENT_ID`、`EMBED_CLIENT_SECRET`、`EMBED_AGENT_ID` 和 `EMBED_ORIGIN`，使用便捷代理接口：

```text
GET /api/agent-token?external_user_id=demo-user
```

该接口从后端环境变量读取 secret，适合本地 Demo。生产环境必须把 `external_user_id` 绑定到业务登录态，不能允许客户端任意指定用户 ID。

## SDK Demo

```bash
cd apps/ai-sdk
npm run build
npm run demo
```

将 demo 中的 `endpoint`、`platformId`、`agentId` 和 `getToken` 改为本地服务配置。浏览器开发者工具应确认 WebSocket URL 不包含 token，首个业务帧为连接后的 `auth`，并在 `session_ready` 后发送 `message_send`。

## 验收路径

1. 验证两个平台、两个 Agent 和两个外部用户的 token 不能跨平台或跨 Agent 使用。
2. 验证流式回答顺序为 `message_started -> message_delta/citation -> message_completed`。
3. 发送期间点击停止，确认后端取消生成且不产生新的完成消息。
4. 在 Redis 窗口内断网重连，确认 auth 游标后补发遗漏事件。
5. 删除或等待 Redis 窗口失效，确认 `recovered=false`，随后仅通过消息快照恢复。
6. 销毁 SDK 后确认 socket、重连 timer、DOM 和事件监听均释放。
